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

# Global active games rooms storage
active_games = {}

# Initial default rooms መፍጠር (ሲስተሙ ሲነሳ ጨዋታዎች እንዲኖሩ)
def init_default_games():
    if not active_games:
        # ለምሳሌ በ 10 ብር እና 20 ብር ስቴክ የሚጀምሩ ሩሞች አስቀድመን እንፈጥራለን
        active_games[1] = BingoGame(1, entry_price=10)
        active_games[2] = BingoGame(2, entry_price=20)

init_default_games()

# ==========================================
# USER ROUTES (Player-facing views)
# ==========================================

@app.route('/')
def index():
    """Lobby ገጽ፡ ያሉትን ጨዋታዎች እና የዩዘርን ባሌንስ ማሳየት"""
    if 'user_id' not in session:
        session['user_id'] = random.randint(100000, 999999)
    
    user = User.query.get(session['user_id'])
    if not user:
        rand_telegram_id = int(session['user_id'])
        user = User(
            id=session['user_id'],
            telegram_id=rand_telegram_id,
            username=f"Player_{session['user_id']}",
            balance=50.0
        )
        db.session.add(user)
        db.session.commit()

    return render_template('game_lobby.html', balance=user.balance)

@app.route('/game/list', methods=['GET'])
def list_games():
    """Available games (waiting rooms) ዝርዝር በ JSON መልክ መመለስ"""
    games_data = []
    for g_id, game in active_games.items():
        if game.status == "waiting":
            games_data.append({
                'id': g_id,
                'players': len(game.players),
                'entry_price': game.entry_price,
                'status': game.status
            })
    return jsonify(games_data)

@app.route('/game/create', methods=['POST'])
def create_game():
    """አዲስ ሩም (Game Room) በባለቤቱ/አድሚኑ ወይም በሲስተሙ ጥያቄ መፍጠር"""
    try:
        entry_price = int(request.json.get('entry_price', 10))
        user_id = session.get('user_id', 1)

        user = User.query.get(user_id)
        user_balance = user.balance if user else 0.0

        if user_balance < entry_price:
            return jsonify({
                'error': 'Insufficient balance! Please top up your wallet first.',
                'low_balance': True
            }), 400

        # አዲስ ሩም መፍጠር
        new_game_id = max(active_games.keys(), default=0) + 1
        active_games[new_game_id] = BingoGame(new_game_id, entry_price)

        return jsonify({
            'success': True,
            'game_id': new_game_id,
            'entry_price': entry_price
        })
    except Exception as e:
        logger.exception(f"Error creating game: {str(e)}")
        return jsonify({'error': 'Failed to create game'}), 500

@app.route('/game/<int:game_id>/select_cartela')
def select_cartela(game_id):
    """ዩዘሩ የተመረጠውን ሩም አግኝቶ ከ 1-100 ካርቴላ የሚመርጥበት ገጽ"""
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    user_id = session.get('user_id', 1)
    user = User.query.get(user_id)
    balance = user.balance if user else 50.0

    # უკვე የተያዙ ካርቴላዎች ዝርዝር
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
    """ዩዘሩ ካርቴላ መርጦ ጨዋታውን የሚቀላቀልበት እና ገንዘብ የሚቀነስበት ሎጂክ"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id', 1)
    data = request.json or {}
    cartela_number = data.get('cartela_number')

    if not cartela_number:
        return jsonify({'error': 'Please select a cartela number'}), 400

    user = User.query.get(user_id)
    user_balance = user.balance if user else 50.0

    # 1. ባሌንስ ማረጋገጥ
    if user_balance < game.entry_price:
        return jsonify({
            'error': 'Insufficient balance! Please top up your wallet first.',
            'low_balance': True
        }), 400

    # 2. የጨዋታውን ዋጋ ከዩዘሩ አካውንት መቀነስ
    if user:
        user.balance -= game.entry_price
        db.session.commit()

    # 3. ተጫዋቹን ጨዋታው ውስጥ መመዝገብ
    board = game.add_player(user_id, cartela_number=int(cartela_number))
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
    """የላይቭ ጨዋታ ማሳያ ገጽ"""
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
    """ቁጥር መጥሪያ ራውት"""
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
    """ቢንጎ ማረጋገጫ ራውት"""
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
# ADMIN ROUTES
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