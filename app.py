import os
import random
import asyncio
import logging
from functools import wraps
from flask import Flask, jsonify, request, session, render_template, redirect, url_for, flash
from datetime import datetime
from database import db, init_db
from game_logic import BingoGame

# Import admin credentials from config
from config import ADMIN_USERNAME, ADMIN_PASSWORD

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Initialize database
init_db(app)

# Import models after db initialization
from models import User, Game, GameParticipant, Transaction

# Game storage (temporary, will be moved to database)
active_games = {}

# ==========================================
# USER ROUTES (Player-facing views)
# ==========================================

@app.route('/')
def index():
    """Show available games or create a new one."""
    if 'user_id' not in session:
        session['user_id'] = random.randint(1, 1000000)  # Temporary user ID generation
    
    # ተጠቃሚውን ከዳታቤዝ መፈለግ ወይም መፍጠር
    user = User.query.get(session['user_id'])
    if not user:
        user = User(id=session['user_id'], username=f"Player_{session['user_id']}", balance=50.0) # ነባሪ የፈተና 50 ብር
        db.session.add(user)
        db.session.commit()

    return render_template('game_lobby.html', balance=user.balance)

@app.route('/game/list', methods=['GET'])
def list_games():
    """Return active games as JSON for lobby refresh"""
    games_data = []
    for g_id, game in active_games.items():
        if game.status == "waiting":
            games_data.append({
                'id': g_id,
                'players': len(game.players),
                'entry_price': game.entry_price
            })
    return jsonify(games_data)

@app.route('/webhook/deposit', methods=['POST'])
def deposit_webhook():
    """Handle deposit webhook from Tasker"""
    try:
        data = request.get_json()
        logger.info(f"Received deposit webhook: {data}")

        if not data or 'amount' not in data or 'phone' not in data:
            error_msg = 'Invalid webhook data - must include amount and phone'
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 400

        try:
            amount = float(data['amount'])
            if amount <= 0:
                return jsonify({'error': 'Amount must be positive'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid amount format'}), 400

        from bot import process_deposit_confirmation
        asyncio.run(process_deposit_confirmation(data))

        return jsonify({'status': 'success', 'message': 'Deposit processed successfully'})

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error processing webhook: {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/webhook/test', methods=['POST'])
def test_webhook():
    """Test endpoint for webhook validation"""
    try:
        data = request.get_json()
        logger.info(f"Test webhook received: {data}")
        logger.debug(f"Request headers: {dict(request.headers)}")

        validation = {
            "format_check": [],
            "data_validation": [],
            "received_data": data,
            "headers": dict(request.headers)
        }

        if not data:
            validation["format_check"].append("❌ No JSON data received")
            return jsonify(validation), 400

        if request.headers.get('X-GitHub-Event') == 'ping':
            return jsonify({
                "message": "Webhook configured successfully!",
                "zen": data.get('zen', 'No zen provided')
            })

        amount = None
        phone = None

        if 'amount' in data and 'phone' in data:
            amount = data.get('amount')
            phone = data.get('phone')
        elif 'issue' in data:
            title = data['issue']['title']
            if 'Deposit:' in title:
                try:
                    parts = title.split('Deposit:')[1].strip().split('-')
                    amount = float(parts[0].strip())
                    phone = parts[1].strip()
                except (IndexError, ValueError):
                    pass

        for field in [('amount', amount), ('phone', phone)]:
            if not field[1]:
                validation["format_check"].append(f"❌ Missing required field: {field[0]}")
            else:
                validation["format_check"].append(f"✅ Found required field: {field[0]}")

        try:
            amount = float(amount) if amount else 0
            if amount <= 0:
                validation["data_validation"].append("❌ Amount must be positive")
            else:
                validation["data_validation"].append(f"✅ Valid amount: {amount}")
        except (ValueError, TypeError):
            validation["data_validation"].append("❌ Invalid amount format")

        if phone:
            phone = str(phone)
            if not phone.isdigit() or len(phone) < 10:
                validation["data_validation"].append("❌ Invalid phone number format")
            else:
                validation["data_validation"].append(f"✅ Valid phone format: {phone}")

        validation["status"] = "valid" if all(
            "❌" not in checks 
            for checks in validation["format_check"] + validation["data_validation"]
        ) else "invalid"

        logger.info(f"Webhook validation result: {validation}")
        return jsonify(validation)

    except Exception as e:
        logger.error(f"Error in webhook test: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "help": "Make sure to send a POST request with Content-Type: application/json"
        }), 500

@app.route('/game/create', methods=['GET', 'POST'])
def create_game():
    """Create a new game room and check user balance before proceeding."""
    try:
        if request.method == 'POST':
            entry_price = int(request.json.get('entry_price', 10))
            user_id = session.get('user_id', 1)

            # 1. የተጠቃሚውን ቀሪ ሂሳብ (Balance) ከዳታቤዝ ማረጋገጥ
            user = User.query.get(user_id)
            user_balance = user.balance if user else 0.0

            if user_balance < entry_price:
                return jsonify({
                    'error': 'Insufficient balance! Please top up your wallet first.',
                    'low_balance': True
                }), 400

            if entry_price not in [10, 20, 50, 100]:
                return jsonify({'error': 'Invalid entry price'}), 400

            # 2. አዲስ ጨዋታ በሲስተም መፍጠር
            game_id = len(active_games) + 1
            active_games[game_id] = BingoGame(game_id, entry_price)

            return jsonify({
                'game_id': game_id,
                'entry_price': entry_price
            })
        else:
            return jsonify({'error': 'Invalid request method'}), 405
    except Exception as e:
        logger.exception(f"Error creating game: {str(e)}")
        return jsonify({'error': 'Failed to create game'}), 500

@app.route('/game/<int:game_id>/select_cartela')
def select_cartela(game_id):
    """Show cartela selection interface with wallet & stake info"""
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    user_id = session.get('user_id', 1)
    user = User.query.get(user_id)
    balance = user.balance if user else 50.0

    used_cartelas = set()
    for player in game.players.values():
        used_cartelas.add(player.get('cartela_number', 0))

    return render_template(
        'cartela_selection.html',
        game_id=game_id,
        entry_price=game.entry_price,
        used_cartelas=used_cartelas,
        balance=balance
    )

@app.route('/game/<int:game_id>/join', methods=['POST'])
def join_game(game_id):
    """Join existing game room using selected cartela number and deduct balance"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id', 1)
    data = request.json or {}
    cartela_number = data.get('cartela_number')

    user = User.query.get(user_id)
    user_balance = user.balance if user else 50.0

    # 1. ባሌንስ ማረጋገጥ
    if user_balance < game.entry_price:
        return jsonify({
            'error': 'Insufficient balance! Please top up your wallet first.',
            'low_balance': True
        }), 400

    # 2. ሂሳብ መቀነስ (Stake deduction)
    if user:
        user.balance -= game.entry_price
        db.session.commit()

    # 3. ተጫዋቹን ጨዋታው ውስጥ መመዝገብ
    board = game.add_player(user_id, cartela_number=cartela_number)
    if not board:
        # ካርቴላው ከተያዘ ገንዘቡን መልሶ መክፈል
        if user:
            user.balance += game.entry_price
            db.session.commit()
        return jsonify({'error': 'Cartela already taken or game full'}), 400

    session['active_game_id'] = game_id

    return jsonify({
        'success': True,
        'game_id': game_id
    })

@app.route('/game/<int:game_id>')
def play_game(game_id):
    """Show the active game interface."""
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    user_id = session.get('user_id', 1)

    if user_id not in game.players:
        return redirect(url_for('index'))

    player = game.players[user_id]

    if game.status == "waiting" and len(game.players) >= game.min_players:
        game.start_game()
        if game.status == "active":
            game.call_number()

    current_number = None
    if game.status == "active" and game.called_numbers:
        current_number = game.format_number(game.called_numbers[-1])

    return render_template('game.html',
                           game_id=game_id,
                           game=game,
                           board=player['board'],
                           marked=player['marked'],
                           called_numbers=game.called_numbers,
                           current_number=current_number,
                           active_players=len(game.players),
                           game_status=game.status,
                           entry_price=game.entry_price)

@app.route('/game/<int:game_id>/call', methods=['POST'])
def call_number(game_id):
    """Call the next number."""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    if game.status != "active":
        return jsonify({'error': 'Game not active'}), 400

    number = game.call_number()
    if number:
        return jsonify({
            'number': number,
            'called_numbers': game.called_numbers
        })
    return jsonify({'error': 'No more numbers to call'}), 400

@app.route('/game/<int:game_id>/mark', methods=['POST'])
def mark_number(game_id):
    """Mark a number on the player's board."""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id', 1)

    if user_id not in game.players:
        return jsonify({'error': 'Player not in game'}), 400

    check_win = request.json.get('check_win', False)
    if check_win:
        winner, message = game.check_winner(user_id)
        if winner:
            game.end_game(user_id)
        return jsonify({
            'winner': winner,
            'message': message
        })

    number = request.json.get('number')
    if not number:
        return jsonify({'error': 'Number required'}), 400

    success = game.mark_number(user_id, number)
    if not success:
        return jsonify({'error': 'Could not mark number'}), 400

    winner, message = game.check_winner(user_id)
    if winner:
        game.end_game(user_id)

    return jsonify({
        'marked': game.players[user_id]['marked'],
        'winner': winner,
        'message': message
    })


# ==========================================
# ADMIN ROUTES (Dashboard & User Management)
# ==========================================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials')
            
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    game_list = list(active_games.values())
    active_count = len([g for g in game_list if hasattr(g, 'status') and g.status == "active"])
    
    users_list = User.query.all()
    
    return render_template(
        'admin/dashboard.html',
        players={}, 
        games=game_list,
        active_games=active_count,
        total_players=len(users_list),
        users=users_list
    )

@app.route('/admin/user/<int:user_id>/add_balance', methods=['POST'])
@admin_required
def admin_add_balance(user_id):
    try:
        amount = float(request.form.get('amount', 0))
        if amount <= 0:
            flash('Amount must be greater than zero', 'error')
            return redirect(url_for('admin_dashboard'))
            
        user = User.query.get(user_id)
        if user:
            user.balance += amount
            db.session.commit()
            flash(f'Successfully added {amount} to user!', 'success')
        else:
            flash('User not found', 'error')
            
    except Exception as e:
        logger.error(f"Error adding balance: {str(e)}")
        flash('Error adding balance', 'error')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)