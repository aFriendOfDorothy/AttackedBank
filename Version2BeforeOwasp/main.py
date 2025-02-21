import re
import logging
import random 
from logging.handlers import RotatingFileHandler
import datetime
import os
import bcrypt
import secrets
import requests
from datetime import timedelta, datetime
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database_manager import DatabaseManager
from user import User
from functools import wraps

app = Flask(__name__)

# --------------------------------------------------------------------------
# 1. Configure Security & Session
# --------------------------------------------------------------------------
# Generate a random secret key at startup.
# In production, you might load this from a secure place like an env variable.
app.secret_key = secrets.token_hex(32)

# Session security settings
app.config.update(
    SESSION_COOKIE_SECURE=False,      # Set to True if you have HTTPS
    SESSION_COOKIE_HTTPONLY=True,     # Prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',    # Helps protect against CSRF
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=5)  # Session expires after 5 minutes of inactivity
)

# --------------------------------------------------------------------------
# 2. Configure Logging (Rotating File Handler)
# --------------------------------------------------------------------------
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log_file = "secure_app.log"
log_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)
# End of logging configuration

# Initialize the database manager
db_manager = DatabaseManager()

def is_strong_password(password):
    """
    Return True if the password is at least 8 characters long,
    and contains uppercase, lowercase, digit, and special character.
    """
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    special_chars_pattern = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]"
    if not re.search(special_chars_pattern, password):
        return False
    return True

def generate_captcha():
    """Generates a simple math CAPTCHA question and stores the answer in the session."""
    if 'captcha_answer' not in session:
        session['captcha_answer'] = ""
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    session['captcha_answer'] = str(num1 + num2)  # Store as string for comparison
    return f"{num1} + {num2} = ?"


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    Handles the user signup:
     - Checks if passwords match (if confirm_password is provided)
     - Ensures username doesn't already exist
     - Enforces strong password requirements
     - Hashes the password with bcrypt
     - Creates the user in the DB
    """
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form.get('confirm_password')
        
        # Check password confirmation
        if confirm_password and password != confirm_password:
            error = "Passwords do not match."
        # Check if user already exists
        elif db_manager.user_exists(username):
            error = "Username already taken, please choose another."
        else:
            # Validate password strength
            if not is_strong_password(password):
                error = (
                    "Password too weak! Must be at least 8 characters and include "
                    "uppercase, lowercase, digits, and special characters."
                )
            else:
                # Hash the password (bcrypt does salting automatically)
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

                # Create user in DB with hashed password (store as utf-8 string)
                db_manager.create_user(username, hashed_password.decode('utf-8'))

                app.logger.info(f"New user created: '{username}' (password hashed)")
                return redirect(url_for('login'))
    return render_template('signup.html', error=error)


limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """
    Handles user login:
    - Uses a simple math CAPTCHA for bot prevention.
    - Validates CAPTCHA answer before processing login.
    """
    user_ip = request.remote_addr  # Get IP
    app.logger.debug(f"Received {request.method} request at /login from {user_ip}")
    error = None

    if request.method == 'GET':
        session['captcha_question'] = generate_captcha()  # Generate CAPTCHA
        return render_template('login.html', error=error)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        captcha_input = request.form.get('captcha')  # Get CAPTCHA answer from user

        if not username or not password or not captcha_input:
            app.logger.warning(f"Missing login credentials from IP {user_ip}.")
            return render_template('login.html', error="Please fill in all fields and complete the CAPTCHA.")


        # CAPTCHA Validation
        if captcha_input.strip() != session.get('captcha_answer'):
            app.logger.warning(f"Failed CAPTCHA for user '{username}' from IP {user_ip}.")
            session['captcha_question'] = generate_captcha()  # Generate new CAPTCHA on failure
            return render_template('login.html', error="Incorrect CAPTCHA. Try again.")

        # Simulated user validation (Replace this with actual DB check)
        if username == "admin" and password == "V3yT@By>%w3[cXlI":
            session.clear()
            session.permanent = True
            session['username'] = username
            session['last_activity'] = datetime.now().timestamp()
            app.logger.info(f"User '{username}' logged in successfully from IP {user_ip}.")
            return redirect(url_for('dashboard'))
        else:
            app.logger.warning(f"Invalid login attempt for user '{username}' from IP {user_ip}.")
            time.sleep(2)  # Introduce delay to slow brute-force attacks
            session['captcha_question'] = generate_captcha()  # Generate new CAPTCHA
            return render_template('login.html', error="Invalid username or password.")

    return render_template('login.html', error=error)




def login_required(f):
    """
    Decorator to ensure the user is logged in (and session hasn't expired) 
    before accessing certain routes (like dashboard).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))

        last_activity = session.get('last_activity')
        if not last_activity:
            session.clear()
            return redirect(url_for('login'))

        # Check if session has timed out
        idle_time = datetime.now().timestamp() - last_activity
        if idle_time > app.config['PERMANENT_SESSION_LIFETIME'].total_seconds():
            session.clear()
            return redirect(url_for('login'))

        # Update the last activity time
        session['last_activity'] = datetime.now().timestamp()
        return f(*args, **kwargs)
    return decorated_function

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    """
    Displays the user dashboard and handles money transfers.
    Only accessible if logged in.
    """
    username = session['username']
    user_row = db_manager.get_user(username)
    if not user_row:
        app.logger.warning(f"Session user '{username}' not found in DB. Logging out.")
        return redirect(url_for('logout'))

    # Create a User object from the DB row
    current_user = User(user_row[0], user_row[1], user_row[2], user_row[3])
    transfer_message = None
    error = None

    if request.method == 'POST':
        target_user_name = request.form['target_user']
        attack_explanation = request.form.get('attack_explanation')  # If admin
        amount_str = request.form.get('amount')

        try:
            amount = float(amount_str)
        except (ValueError, TypeError):
            error = "Invalid amount."
            app.logger.debug(f"User '{username}' entered invalid amount '{amount_str}'")
            return render_template(
                'dashboard.html',
                username=current_user.username,
                balance=current_user.balance,
                transfer_message=transfer_message,
                error=error
            )

        # If the amount exceeds 10,000, adjust it and notify the user
        MAX_TRANSFER_AMOUNT = 10_000
        if amount > MAX_TRANSFER_AMOUNT:
            amount = MAX_TRANSFER_AMOUNT
            error = f"Maximum transfer limit is {MAX_TRANSFER_AMOUNT}. Amount adjusted to {MAX_TRANSFER_AMOUNT}."
            app.logger.warning(f"User '{username}' attempted to transfer more than {MAX_TRANSFER_AMOUNT}.")

        # If admin, require explanation
        if current_user.username == 'admin':
            if not attack_explanation or not attack_explanation.strip():
                error = "Admin must provide an explanation of how attackers got in."
                return render_template(
                    'dashboard.html',
                    username=current_user.username,
                    balance=current_user.balance,
                    transfer_message=transfer_message,
                    error=error
                )
            else:
                # Append the explanation to a log file
                log_filename = "attack_log.txt"
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entry = f"[{timestamp}] Admin Explanation: {attack_explanation}\n"
                with open(log_filename, "a", encoding="utf-8") as f:
                    f.write(log_entry)
                app.logger.info("Admin provided an attack explanation.")

        if amount <= 0:
            error = "Transfer amount must be greater than 0."
        elif amount > current_user.balance:
            error = "Insufficient balance."
            app.logger.warning(f"User '{username}' attempted to transfer more than their balance.")
        else:
            target_row = db_manager.get_user(target_user_name)
            if not target_row:
                error = f"User '{target_user_name}' does not exist."
                app.logger.warning(f"User '{username}' attempted transfer to non-existent user '{target_user_name}'.")
            else:
                # Perform the transfer
                current_user.withdraw(amount)
                db_manager.update_balance(current_user.username, current_user.balance)

                target_user = User(target_row[0], target_row[1], target_row[2], target_row[3])
                target_user.deposit(amount)
                db_manager.update_balance(target_user.username, target_user.balance)

                transfer_message = f"Successfully transferred {amount} to {target_user_name}!"
                app.logger.info(
                    f"User '{username}' transferred {amount} to '{target_user_name}'. "
                    f"New balance: {current_user.balance}"
                )

    return render_template(
        'dashboard.html',
        username=current_user.username,
        balance=current_user.balance,
        transfer_message=transfer_message,
        error=error
    )


@app.route('/logout')
def logout():
    user = session.pop('username', None)
    if user:
        app.logger.info(f"User '{user}' logged out.")
    return redirect(url_for('login'))

# For demonstration, you could enable simple IP whitelisting (commented out):
# @app.before_request
# def limit_remote_addr():
#     allowed_ips = ["127.0.0.1"]
#     if request.remote_addr not in allowed_ips:
#         abort(403)  # Forbidden

if __name__ == '__main__':
    # In production, set debug=False and run behind a production server
    app.run(host='0.0.0.0', port=5001, debug=False)
