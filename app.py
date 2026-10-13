import os
import random
import json
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
        active_games[1] = BingoGame(1, entry_price=10, max_cards_per_player=4)
        active_games[2] = BingoGame(2, entry_price=20, max_cards_per_player=4)

init_default_games()

# ==========================================
# USER ROUTES (Player-facing views)
# ==========================================

@app.route('/')
def index():
    """Lobby ገጽ፡ ያሉትን ጨዋታዎች እና የዩዘርን ባሌንስ ማሳየት[cite: 8]"""
    if not session.get('user_id'):
        session['user_id'] = random.randint(100000, 999999)
    
    user_id = int(session['user_id'])
    
    user = User.query.get(user_id)
    if not user:
        user = User(
            id=user_id,
            telegram_id=user_id,
            username=f"Player_{user_id}",
            balance=50.0,
            is_blocked=False
        )
        db.session.add(user)
        db.session.commit()
        
    if user.is_blocked:
        return "Your account has been blocked by the administrator.", 403

    return render_template('game_lobby.html', balance=user.balance)

@app.route('/game/list', methods=['GET'])
def list_games():
    """Available games (waiting rooms) ዝርዝር በ JSON መልክ መመለስ[cite: 8]"""
    games_data = []
    for g_id, game in active_games.items():
        if game.status == "waiting":
            games_data.append({
                'id': g_id,
                'players': len(game.players),
                'total_cards': game.get_total_cards(),
                'entry_price': game.entry_price,
                'status': game.status
            })
    return jsonify(games_data)

@app.route('/game/create', methods=['POST'])
def create_game():
    """አዲስ ሩም (Game Room) መፍጠር (እስከ 3 አክቲቭ ሩሞች ብቻ እንዲኖሩ መቆጣጠር)[cite: 8]"""
    try:
        entry_price = int(request.json.get('entry_price', 10))
        if not session.get('user_id'):
            session['user_id'] = random.randint(100000, 999999)
        user_id = int(session['user_id'])

        user = User.query.get(user_id)
        if user and user.is_blocked:
            return jsonify({'error': 'Your account is blocked.'}), 403

        # በአותו Entry Price ያሉ waiting/active ሩሞችን መቁጠር (ቢበዛ 3 መሆን አለበት)
        same_price_games = [
            g for g in active_games.values() 
            if g.entry_price == entry_price and g.status in ['waiting', 'active']
        ]

        if len(same_price_games) >= 3:
            available_game = next((g for g in same_price_games if g.status == 'waiting'), None)
            if available_game:
                return jsonify({'success': True, 'game_id': available_game.game_id, 'entry_price': entry_price})
            else:
                return jsonify({'error': 'Maximum 3 active games running for this room. Please wait.'}), 400

        user_balance = user.balance if user else 0.0

        if user_balance < entry_price:
            return jsonify({
                'error': 'Insufficient balance! Please top up your wallet first.',
                'low_balance': True
            }), 400

        new_game_id = max(active_games.keys(), default=0) + 1
        active_games[new_game_id] = BingoGame(new_game_id, entry_price, max_cards_per_player=4)

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
    """ዩዘሩ የተመረጠውን ሩም አግኝቶ ከ 1-200 ካርቴላ የሚመርጥበት ገጽ[cite: 8]"""
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    if not session.get('user_id'):
        session['user_id'] = random.randint(100000, 999999)
    user_id = int(session['user_id'])
    
    user = User.query.get(user_id)
    if user and user.is_blocked:
        return "Your account has been blocked.", 403

    balance = user.balance if user else 50.0

    used_cartelas = set()
    for cards in game.players.values():
        for card in cards:
            used_cartelas.add(card.get('cartela_number', 0))

    return render_template(
        'cartela_selection.html',
        game_id=game_id,
        entry_price=game.entry_price,
        used_cartelas=used_cartelas,
        balance=balance
    )

@app.route('/game/<int:game_id>/join', methods=['POST'])
def join_game(game_id):
    """ዩዘሩ ካርቴላ መርጦ ጨዋታውን የሚቀላቀልበት እና ገንዘብ የሚቀነስበት ሎጂክ[cite: 8]"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    if not session.get('user_id'):
        session['user_id'] = random.randint(100000, 999999)
    user_id = int(session['user_id'])
    
    user = User.query.get(user_id)
    if user and user.is_blocked:
        return jsonify({'error': 'Your account is blocked.'}), 403

    data = request.json or {}
    cartela_number = data.get('cartela_number')

    if not cartela_number:
        return jsonify({'error': 'Please select a cartela number'}), 400

    user_balance = user.balance if user else 50.0

    if user_balance < game.entry_price:
        return jsonify({
            'error': 'Insufficient balance! Please top up your wallet first.',
            'low_balance': True
        }), 400

    if user:
        user.balance -= game.entry_price
        db.session.commit()

    username = user.username if user else "Player"
    success, msg, board = game.add_player_card(user_id, username=username, cartela_number=int(cartela_number))
    if not success:
        if user:
            user.balance += game.entry_price
            db.session.commit()
        return jsonify({'error': msg}), 400

    session['active_game_id'] = game_id

    return jsonify({
        'success': True,
        'game_id': game_id
    })

@app.route('/game/<int:game_id>')
def play_game(game_id):
    """የላይቭ ጨዋታ ማሳያ ገጽ[cite: 8]"""
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    if not session.get('user_id'):
        session['user_id'] = random.randint(100000, 999999)
    user_id = int(session['user_id'])

    user = User.query.get(user_id)
    if user and user.is_blocked:
        return "Your account has been blocked.", 403

    if user_id not in game.players or not game.players[user_id]:
        return redirect(url_for('index'))

    player_cards = game.players[user_id]

    if game.status == "waiting" and len(game.players) >= game.min_players:
        game.start_game()

    current_number = None
    if game.status == "active" and game.called_numbers:
        current_number = game.format_number(game.called_numbers[-1])

    pool, bonus_text = game.update_pool_and_bonus()

    return render_template('game.html',
                           game_id=game_id,
                           game=game,
                           player_cards=player_cards,
                           called_numbers=[game.format_number(n) for n in game.called_numbers],
                           current_number=current_number,
                           active_players=len(game.players),
                           total_cards=game.get_total_cards(),
                           game_status=game.status,
                           entry_price=game.entry_price,
                           pool=round(pool, 2),
                           bonus=bonus_text)

@app.route('/game/<int:game_id>/status', methods=['GET'])
def game_status_api(game_id):
    """የጨዋታውን ወቅታዊ መረጃዎች በእውነተኛ ሰዓት (Real-time) መመለስ[cite: 8]"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    pool, bonus_text = game.update_pool_and_bonus()
    
    # Format called numbers
    formatted_called = [game.format_number(n) for n in game.called_numbers]
    
    # Winner info formatting for frontend modal
    formatted_winners = []
    for w in game.winners:
        formatted_winners.append({
            'user_id': w['user_id'],
            'username': w['username'],
            'cartela_number': w['cartela_number'],
            'board': w['board'],
            'marked': w['marked']
        })

    prize_per_winner = round(pool / len(game.winners), 2) if game.winners else 0.0

    return jsonify({
        'game_id': game.game_id,
        'active_players': len(game.players),
        'total_cards': game.get_total_cards(),
        'pool': round(pool, 2),
        'bonus': bonus_text,
        'status': game.status,
        'called_numbers': formatted_called,
        'current_call': formatted_called[-1] if formatted_called else '---',
        'winners': formatted_winners,
        'prize_per_winner': prize_per_winner
    })

@app.route('/game/<int:game_id>/call', methods=['POST'])
def call_number(game_id):
    """ቁጥር መጥሪያ ራውት[cite: 8]"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    if game.status != "active":
        return jsonify({'error': 'Game not active'}), 400

    number = game.call_number()
    if number:
        return jsonify({
            'number': number,
            'called_numbers': [game.format_number(n) for n in game.called_numbers]
        })
    return jsonify({'error': 'No more numbers to call'}), 400

@app.route('/game/<int:game_id>/mark', methods=['POST'])
def mark_number(game_id):
    """ቢንጎ ማረጋገጫ እና ምልክት ማድረጊያ ራውት[cite: 8]"""
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    if not session.get('user_id'):
        session['user_id'] = random.randint(100000, 999999)
    user_id = int(session['user_id'])

    user = User.query.get(user_id)
    if user and user.is_blocked:
        return jsonify({'error': 'Your account is blocked.'}), 403

    if user_id not in game.players:
        return jsonify({'error': 'Player not in game'}), 400

    data = request.json or {}
    card_index = int(data.get('card_index', 0))
    check_win = data.get('check_win', False)

    if check_win:
        winner, message, prize_per_winner = game.claim_bingo(user_id, card_index)
        if winner:
            if user:
                user.balance += prize_per_winner
                db.session.commit()
        return jsonify({
            'winner': winner,
            'message': message,
            'prize': prize_per_winner,
            'winners': game.winners
        })

    number = data.get('number')
    if not number:
        return jsonify({'error': 'Number required'}), 400

    success = game.mark_number(user_id, card_index, int(number))
    if not success:
        return jsonify({'error': 'Could not mark number'}), 400

    winner, message, prize_per_winner = game.claim_bingo(user_id, card_index)
    if winner:
        if user:
            user.balance += prize_per_winner
            db.session.commit()

    return jsonify({
        'marked': game.players[user_id][card_index]['marked'],
        'winner': winner,
        'message': message,
        'prize': prize_per_winner if winner else 0.0,
        'winners': game.winners
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
    
    pending_ws = Transaction.query.filter_by(type='withdraw', status='pending').all()
    all_txs = Transaction.query.order_by(Transaction.id.desc()).limit(20).all()
    
    return render_template(
        'admin/dashboard.html',
        players={}, 
        games=game_list,
        active_games=active_count,
        total_players=len(users_list),
        users=users_list,
        pending_withdrawals=pending_ws,
        transactions=all_txs
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

@app.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def admin_approve_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Withdrawal request approved successfully!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/withdrawal/<int:tx_id>/reject', methods=['POST'])
@admin_required
def admin_reject_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'rejected'
        user = User.query.get(tx.user_id)
        if user:
            user.balance += abs(tx.amount)
        db.session.commit()
        flash('Withdrawal request rejected and refunded to user.', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<int:user_id>/toggle_block', methods=['POST'])
@admin_required
def admin_toggle_block(user_id):
    user = User.query.get(user_id)
    if user:
        user.is_blocked = not user.is_blocked
        db.session.commit()
        status_msg = "blocked" if user.is_blocked else "unblocked"
        flash(f'User successfully {status_msg}!', 'success')
    else:
        flash('User not found.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/broadcast', methods=['POST'])
@admin_required
def admin_broadcast_news():
    text = request.form.get('broadcast_text')
    if text:
        flash('Broadcast message sent successfully to users!', 'success')
    else:
        flash('Broadcast text cannot be empty.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_welcome_image', methods=['POST'])
@admin_required
def admin_update_welcome_image():
    image_url = request.form.get('image_url')
    if image_url:
        config_file = "bot_config.json"
        config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
        config['welcome_image_file_id'] = image_url
        with open(config_file, 'w') as f:
            json.dump(config, f)
        flash('Welcome image updated successfully!', 'success')
    else:
        flash('Image URL cannot be empty.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)