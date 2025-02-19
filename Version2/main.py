# main.py
import re
import logging
from flask import Flask, request, redirect, url_for, session, render_template, jsonify
from database_manager import DatabaseManager
from user import User

app = Flask(__name__)
app.secret_key = 'SOME_SECRET_KEY'  # Replace with a secure random value in production

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

    # You can customize this list of special characters
    special_chars_pattern = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]"
    if not re.search(special_chars_pattern, password):
        return False

    return True

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if user already exists
        if db_manager.user_exists(username):
            error = "Username already taken, please choose another."
        else:
            # Enforce strong password requirement
            if not is_strong_password(password):
                error = (
                    "Password too weak! Must be at least 8 characters and include "
                    "uppercase, lowercase, digits, and special characters."
                )
            else:
                # Create user in DB if password is strong
                db_manager.create_user(username, password)
                return redirect(url_for('login'))

    return render_template('signup.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    logging.debug(f"Received {request.method} request at /login")
    error = None

    if request.method == 'POST':
        logging.debug(f"Headers: {request.headers}")
        logging.debug(f"Raw Request Data: {request.data}")

        # Determine if request is JSON or Form data
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            logging.debug(f"Received JSON data: {data}")
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            logging.debug(f"Received Form Data - Username: {username}, Password: {password}")

        # Ensure username and password were received
        if not username or not password:
            logging.debug("Missing username or password")
            return jsonify({"error": "Missing username or password"}), 400

        # Validate credentials
        user_row = db_manager.validate_credentials(username, password)
        if user_row:
            session['username'] = user_row[0]
            logging.debug("Login successful! Redirecting to dashboard.")
            return redirect(url_for('dashboard'))
        else:
            logging.debug("Invalid username or password")
            error = "Invalid username or password."

    return render_template('login.html', error=error)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """Display and handle money transfers."""
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user_row = db_manager.get_user(username)
    if not user_row:
        return redirect(url_for('logout'))

    current_user = User(user_row[0], user_row[1], user_row[2], user_row[3])
    transfer_message = None
    error = None

    if request.method == 'POST':
        target_user_name = request.form['target_user']
        # Attack explanation required if user is admin
        attack_explanation = request.form.get('attack_explanation')  # Could be None if the field doesn't exist

        try:
            amount = float(request.form['amount'])
        except ValueError:
            error = "Invalid amount."
            return render_template(
                'dashboard.html',
                username=current_user.username,
                balance=current_user.balance,
                transfer_message=transfer_message,
                error=error
            )

        # If admin, require the explanation field
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

        if amount <= 0:
            error = "Transfer amount must be greater than 0."
        elif amount > current_user.balance:
            error = "Insufficient balance."
        else:
            # Check if target user exists
            target_row = db_manager.get_user(target_user_name)
            if not target_row:
                error = f"User '{target_user_name}' does not exist."
            else:
                # Perform the transfer
                current_user.withdraw(amount)
                db_manager.update_balance(current_user.username, current_user.balance)

                target_user = User(target_row[0], target_row[1], target_row[2], target_row[3])
                target_user.deposit(amount)
                db_manager.update_balance(target_user.username, target_user.balance)

                transfer_message = f"Successfully transferred {amount} to {target_user_name}!"

    # Render the dashboard
    return render_template(
        'dashboard.html',
        username=current_user.username,
        balance=current_user.balance,
        transfer_message=transfer_message,
        error=error
    )

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Run the Flask application
    app.run(host='0.0.0.0', port=5000, debug=True)
