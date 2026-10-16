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

# Initial default rooms
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
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return "Please open this game through the Telegram Bot (@EdilBingoBot).", 403
    
    user_id = int(user_id)
    session['user_id'] = user_id
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return "User not registered. Please start the Telegram bot first.", 403
        
    if user.is_blocked:
        return "Your account has been blocked by the administrator.", 403

    total_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)
    return render_template('index.html', balance=total_balance, main_balance=user.balance, bonus_balance=user.bonus_balance, coin=user.coin)

@app.route('/scores')
def scores():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    top_scores = User.query.order_by(User.games_won.desc()).limit(10).all()
    return render_template('scores.html', top_scores=top_scores)

@app.route('/history')
def history():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    game_history = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.id.desc()).limit(15).all()
    return render_template('history.html', game_history=game_history)

@app.route('/wallet')
def wallet():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    user = User.query.filter_by(telegram_id=user_id).first()
    balance = (user.balance or 0.0) + (user.bonus_balance or 0.0) if user else 0.0
    return render_template('wallet.html', balance=balance)

@app.route('/profile')
def profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    user = User.query.filter_by(telegram_id=user_id).first()
    return render_template('profile.html', user=user)

@app.route('/game/list', methods=['GET'])
def list_games():
    games_data = []
    for g_id, game in active_games.items():
        if game.status in ["waiting", "countdown", "active"]:
            games_data.append({
                'id': g_id,
                'players': len(game.players),
                'total_cards': game.get_total_cards(),
                'entry_price': game.entry_price,
                'status': game.status,
                'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 30
            })
    return jsonify(games_data)

@app.route('/game/create', methods=['POST'])
def create_game():
    try:
        data = request.json or {}
        entry_price = int(data.get('entry_price', 10))
        user_id = data.get('user_id') or session.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'Unauthorized user'}), 401

        user = User.query.filter_by(telegram_id=int(user_id)).first()
        if not user or user.is_blocked:
            return jsonify({'error': 'User not found or blocked.'}), 403

        if not user.phone:
            return jsonify({'error': 'እባክዎ መጫወት ከመጀመርዎ በፊት በቦቱ በኩል ስልክ ቁጥርዎን ይመዝገቡ (Register).'}), 400

        waiting_game = next((g for g in active_games.values() if g.entry_price == entry_price and g.status == 'waiting'), None)
        if waiting_game:
            return jsonify({
                'success': True,
                'game_id': waiting_game.game_id,
                'entry_price': entry_price
            })

        total_user_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)

        if total_user_balance < entry_price:
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
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
        
    user_id = int(user_id)
    session['user_id'] = user_id
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return "Access denied.", 403

    if not user.phone:
        return "እባክዎ መጫወት ከመጀመርዎ በፊት በቦቱ በኩል ስልክ ቁጥርዎን ይመዝገቡ (Register).", 400

    total_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)

    used_cartelas = set()
    for cards in game.players.values():
        for card in cards:
            used_cartelas.add(card.get('cartela_number', 0))

    return render_template(
        'cartela_selection.html',
        game_id=game_id,
        entry_price=game.entry_price,
        used_cartelas=used_cartelas,
        balance=total_balance
    )

@app.route('/game/<int:game_id>/join', methods=['POST'])
def join_game(game_id):
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return jsonify({'error': 'Your account is blocked or not found.'}), 403

    if not user.phone:
        return jsonify({'error': 'እባክዎ መጫወት ከመጀመርዎ በፊት በቦቱ በኩል ስልክ ቁጥርዎን ይመዝገቡ (Register).'}), 400

    data = request.json or {}
    cartela_number = data.get('cartela_number')

    if not cartela_number:
        return jsonify({'error': 'Please select a cartela number'}), 400

    total_user_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)
    if total_user_balance < game.entry_price:
        return jsonify({
            'error': 'Insufficient balance! Please top up your wallet first.',
            'low_balance': True
        }), 400

    remaining_cost = float(game.entry_price)
    if user.bonus_balance >= remaining_cost:
        user.bonus_balance -= remaining_cost
        remaining_cost = 0.0
    else:
        remaining_cost -= user.bonus_balance
        user.bonus_balance = 0.0
        user.balance -= remaining_cost

    earned_coins = int(game.entry_price // 10)
    user.coin = (user.coin or 0) + earned_coins

    if user.coin >= 10:
        conversion_count = user.coin // 10
        user.bonus_balance += conversion_count * 10.0
        user.coin %= 10

    db.session.commit()

    username = user.username or "Player"
    success, msg, board = game.add_player_card(user.telegram_id, username=username, cartela_number=int(cartela_number))
    if not success:
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
    if game_id not in active_games:
        return redirect(url_for('index'))

    game = active_games[game_id]
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))

    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return "Access denied.", 403

    if not user.phone:
        return "እባክዎ መጫወት ከመጀመርዎ በፊት በቦቱ በኩል ስልክ ቁጥርዎን ይመዝገቡ (Register).", 400

    player_cards = game.players.get(user.telegram_id, [])

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
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    game.update_active_game()
    pool, bonus_text = game.update_pool_and_bonus()
    formatted_called = [game.format_number(n) for n in game.called_numbers]
    
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
        'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 0,
        'called_numbers': formatted_called,
        'current_call': formatted_called[-1] if formatted_called else '---',
        'winners': formatted_winners,
        'prize_per_winner': prize_per_winner
    })

@app.route('/game/<int:game_id>/call', methods=['POST'])
def call_number(game_id):
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
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return jsonify({'error': 'Your account is blocked or not found.'}), 403

    if user.telegram_id not in game.players:
        return jsonify({'error': 'Player not in game'}), 400

    data = request.json or {}
    card_index = int(data.get('card_index', 0))
    check_win = data.get('check_win', False)

    if check_win:
        winner, message, prize_per_winner = game.claim_bingo(user.telegram_id, card_index)
        if winner:
            if user:
                user.balance += prize_per_winner
                user.games_won += 1
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

    success = game.mark_number(user.telegram_id, card_index, int(number))
    if not success:
        return jsonify({'error': 'Could not mark number'}), 400

    winner, message, prize_per_winner = game.claim_bingo(user.telegram_id, card_index)
    if winner:
        if user:
            user.balance += prize_per_winner
            user.games_won += 1
            db.session.commit()

    return jsonify({
        'marked': game.players[user.telegram_id][card_index]['marked'],
        'winner': winner,
        'message': message,
        'prize': prize_per_winner if winner else 0.0,
        'winners': game.winners
    })

@app.route('/game/<int:game_id>/leave', methods=['POST'])
def leave_game(game_id):
    try:
        if game_id not in active_games:
            return jsonify({'success': True})
        game = active_games[game_id]
        user_id = session.get('user_id')
        if user_id:
            user = User.query.filter_by(telegram_id=user_id).first()
            if user and user.telegram_id in game.players:
                success, msg, balance_deducted = game.player_leave(user.telegram_id)
                if balance_deducted:
                    if user.balance >= game.entry_price:
                        user.balance -= game.entry_price
                    else:
                        remainder = game.entry_price - user.balance
                        user.balance = 0.0
                        user.bonus_balance = max(0.0, user.bonus_balance - remainder)
                    db.session.commit()
        session.pop('active_game_id', None)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f"Error in leave_game: {str(e)}")
        return jsonify({'error': 'Failed'}), 500

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
    active_count = len([g for g in game_list if hasattr(g, 'status') and g.status in ["active", "countdown"]])
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

@app.route('/admin/user/<int:user_id>/update', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    try:
        user = User.query.get(user_id)
        if user:
            user.balance = float(request.form.get('balance', user.balance))
            user.bonus_balance = float(request.form.get('bonus_balance', user.bonus_balance))
            user.coin = int(request.form.get('coin', user.coin))
            db.session.commit()
            flash('User balances updated successfully!', 'success')
        else:
            flash('User not found', 'error')
    except Exception as e:
        logger.error(f"Error updating user balances: {str(e)}")
        flash('Error updating user balances', 'error')
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
        flash('Withdrawal request rejected and refunded to user main balance.', 'success')
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
    git_msg = 'Broadcast message sent successfully to users!'
    text = request.form.get('broadcast_text')
    if text:
        flash(git_msg, 'success')
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

@app.route('/ping')
def ping():
    return "Bot and Web are alive!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)