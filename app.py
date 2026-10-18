import os
import random
import json
import logging
import hashlib
from functools import wraps
from flask import Flask, jsonify, request, session, render_template, redirect, url_for, flash
from datetime import datetime, date, timedelta
from database import db, init_db
from game_logic import BingoGame
from config import ADMIN_USERNAME, ADMIN_PASSWORD

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

init_db(app)

from models import User, Game, GameParticipant, Transaction, Transfer, GameHistory, Admin

# Auto-create default admin and ensure tables exist on startup
with app.app_context():
    db.create_all()
    try:
        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            default_admin = Admin(
                username=ADMIN_USERNAME,
                password_hash=hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest(),
                is_super=True
            )
            db.session.add(default_admin)
            db.session.commit()
    except Exception as e:
        logger.exception(f"Error creating default admin: {e}")

active_games = {}

# Rooms Setup: 10, 20, 50, 100 ETB and Demo (999)
def init_default_games():
    if not active_games:
        active_games[1] = BingoGame(1, entry_price=10, max_cards_per_player=4)
        active_games[2] = BingoGame(2, entry_price=20, max_cards_per_player=4)
        active_games[3] = BingoGame(3, entry_price=50, max_cards_per_player=4)
        active_games[4] = BingoGame(4, entry_price=100, max_cards_per_player=4)
        active_games[999] = BingoGame(999, entry_price=0, max_cards_per_player=5)

init_default_games()

CONFIG_FILE = "bot_config.json"
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

# ==========================================
# USER ROUTES (Player-facing views - English)
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

    return render_template('game_lobby.html', balance=user.balance, bonus_balance=user.bonus_balance, coin=user.coin)

@app.route('/scores')
def scores():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    return render_template('scores.html')

@app.route('/scores/data', methods=['GET'])
def scores_data():
    timeframe = request.args.get('timeframe', 'today')
    now = datetime.utcnow()
    
    query = db.session.query(
        User.id,
        User.username,
        User.phone,
        db.func.count(GameHistory.id).label('win_count')
    ).join(GameHistory, User.id == GameHistory.winner_id)
    
    if timeframe == 'today':
        start_date = datetime(now.year, now.month, now.day)
        query = query.filter(GameHistory.created_at >= start_date)
    elif timeframe == 'week':
        start_date = now - timedelta(days=7)
        query = query.filter(GameHistory.created_at >= start_date)
    elif timeframe == 'month':
        start_date = datetime(now.year, now.month, 1)
        query = query.filter(GameHistory.created_at >= start_date)
        
    results = query.group_by(User.id).order_by(db.desc('win_count')).all()
    
    scores_list = []
    for r in results:
        phone_masked = "**********"
        if r.phone and len(str(r.phone)) >= 7:
            p_str = str(r.phone)
            phone_masked = p_str[:5] + "**" + p_str[7:]
        elif r.phone:
            phone_masked = r.phone[:3] + "**"
        else:
            phone_masked = "25190**00000"
            
        scores_list.append({
            'username': r.username or 'Player',
            'phone': phone_masked,
            'wins': r.win_count
        })
        
    return jsonify({'scores': scores_list})

@app.route('/history')
def history():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return redirect(url_for('index'))
    
    game_history = GameHistory.query.filter_by(winner_id=user.id).order_by(GameHistory.id.desc()).limit(20).all()
    return render_template('history.html', game_history=game_history)

@app.route('/wallet')
def wallet():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    user = User.query.filter_by(telegram_id=user_id).first()
    return render_template('wallet.html', balance=user.balance if user else 0.0, bonus_balance=user.bonus_balance if user else 0.0)

@app.route('/profile')
def profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
    user = User.query.filter_by(telegram_id=user_id).first()
    return render_template('profile.html', user=user, balance=user.balance, bonus_balance=user.bonus_balance, games_played=user.games_played, games_won=user.games_won, username=user.username, user_id=user.telegram_id)

@app.route('/game/list', methods=['GET'])
def list_games():
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first() if user_id else None
    
    games_data = []
    for g_id, game in active_games.items():
        if game.entry_price >= 0 and game.status in ["waiting", "countdown", "active", "playing"]:
            user_joined = user and (user.telegram_id in game.players)
            pool, _ = game.update_pool_and_bonus()
            games_data.append({
                'id': g_id,
                'unique_code': getattr(game, 'unique_code', str(g_id)),
                'players': len(game.players),
                'total_cards': game.get_total_cards(),
                'entry_price': game.entry_price,
                'status': game.status,
                'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 30,
                'jackpot_pool': round(pool, 2),
                'user_joined': user_joined
            })
    return jsonify({
        'games': games_data,
        'user_balance': user.balance if user else 0.0,
        'user_bonus': user.bonus_balance if user else 0.0
    })

@app.route('/game/create', methods=['POST'])
def create_game():
    try:
        data = request.json or {}
        entry_price = int(data.get('entry_price', 10))
        requested_game_id = data.get('game_id')
        user_id = data.get('user_id') or session.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'Unauthorized user'}), 401

        user = User.query.filter_by(telegram_id=int(user_id)).first()
        if not user or user.is_blocked:
            return jsonify({'error': 'User not found or blocked.'}), 403

        if entry_price == 0 or requested_game_id == 999:
            game = active_games.get(999)
            if not game:
                game = BingoGame(999, entry_price=0, max_cards_per_player=5)
                active_games[999] = game
            
            has_cartela = user.telegram_id in game.players and len(game.players[user.telegram_id]) > 0
            return jsonify({
                'success': True,
                'game_id': 999,
                'entry_price': 0,
                'has_cartela': has_cartela
            })

        if not user.phone:
            return jsonify({'error': 'Please register your phone number before playing.'}), 400

        waiting_game = next((g for g in active_games.values() if g.entry_price == entry_price and g.status in ['waiting', 'countdown']), None)
        if waiting_game:
            has_cartela = user.telegram_id in waiting_game.players and len(waiting_game.players[user.telegram_id]) > 0
            return jsonify({
                'success': True,
                'game_id': waiting_game.game_id,
                'entry_price': entry_price,
                'has_cartela': has_cartela
            })

        total_user_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)
        if total_user_balance < entry_price:
            return jsonify({'error': 'Insufficient balance! Please top up your wallet first.'}), 400

        new_game_id = max(active_games.keys(), default=0) + 1
        if new_game_id == 999:
            new_game_id = 1000
        active_games[new_game_id] = BingoGame(new_game_id, entry_price, max_cards_per_player=4)

        return jsonify({
            'success': True,
            'game_id': new_game_id,
            'entry_price': entry_price,
            'has_cartela': False
        })
    except Exception as e:
        logger.exception(f"Error creating game: {str(e)}")
        return jsonify({'error': 'Failed to create game'}), 500

@app.route('/game/<game_id>/select_cartela')
def select_cartela(game_id):
    try:
        g_id = int(game_id)
    except ValueError:
        g_id = 999

    if g_id not in active_games:
        entry = 0 if g_id == 999 else 10
        active_games[g_id] = BingoGame(g_id, entry_price=entry, max_cards_per_player=5 if entry == 0 else 4)

    game = active_games[g_id]
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return redirect(url_for('index'))
        
    user_id = int(user_id)
    session['user_id'] = user_id
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return "Access denied.", 403

    if user.telegram_id in game.players and len(game.players[user.telegram_id]) > 0:
        return redirect(url_for('play_game', game_id=g_id))

    used_cartelas = set()
    for cards in game.players.values():
        for card in cards:
            used_cartelas.add(card.get('cartela_number', 0))

    if not hasattr(game, 'static_hash_key') or not game.static_hash_key:
        raw_str = f"edil_bingo_room_{g_id}_{game.entry_price}_{datetime.utcnow().date()}"
        game.static_hash_key = hashlib.sha256(raw_str.encode()).hexdigest()

    return render_template(
        'cartela_selection.html',
        game_id=g_id,
        entry_price=game.entry_price,
        used_cartelas=used_cartelas,
        balance=user.balance,
        bonus=user.bonus_balance,
        game_hash=game.static_hash_key,
        is_demo=(game.entry_price == 0)
    )

@app.route('/game/<int:game_id>/join', methods=['POST'])
def join_game(game_id):
    if game_id not in active_games:
        entry = 0 if game_id == 999 else 10
        active_games[game_id] = BingoGame(game_id, entry_price=entry, max_cards_per_player=5 if entry == 0 else 4)

    game = active_games[game_id]
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user or user.is_blocked:
        return jsonify({'error': 'Your account is blocked or not found.'}), 403

    data = request.json or {}
    cartela_numbers = data.get('cartela_numbers') or [data.get('cartela_number')]
    cartela_numbers = [int(c) for c in cartela_numbers if c is not None]

    if not cartela_numbers:
        return jsonify({'error': 'Please select at least one cartela number'}), 400

    if user.telegram_id in game.players and len(game.players[user.telegram_id]) > 0:
        session['active_game_id'] = game_id
        return jsonify({'success': True, 'game_id': game_id})

    existing_cards_count = len(game.players.get(user.telegram_id, []))
    if existing_cards_count + len(cartela_numbers) > game.max_cards_per_player:
        return jsonify({'error': f'Maximum allowed cartelas is {game.max_cards_per_player}!'}), 400

    total_cost = game.entry_price * len(cartela_numbers)

    if game.entry_price == 0 or game_id == 999:
        username = user.username or "Player"
        for c_num in cartela_numbers:
            game.add_player_card(user.telegram_id, username=username, cartela_number=c_num)
        session['active_game_id'] = game_id
        return jsonify({'success': True, 'game_id': game_id})

    total_user_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)
    if total_user_balance < total_cost:
        return jsonify({'error': 'Insufficient balance for selected cartelas!'}), 400

    if user.balance >= total_cost:
        user.balance -= total_cost
    else:
        remainder = total_cost - user.balance
        user.balance = 0.0
        user.bonus_balance -= remainder
    db.session.commit()

    username = user.username or "Player"
    for c_num in cartela_numbers:
        success, msg, board = game.add_player_card(user.telegram_id, username=username, cartela_number=c_num)
        if not success:
            return jsonify({'error': msg}), 400

    session['active_game_id'] = game_id
    return jsonify({'success': True, 'game_id': game_id})

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

    player_cards = game.players.get(user.telegram_id, [])
    pool, bonus_text = game.update_pool_and_bonus()

    return render_template('game.html',
                           game_id=game_id,
                           game=game,
                           player_cards=player_cards,
                           called_numbers=[game.format_number(n) for n in game.called_numbers],
                           active_players=len(game.players),
                           game_status=game.status,
                           entry_price=game.entry_price,
                           pool=round(pool, 2),
                           bonus=bonus_text,
                           balance=user.balance)

@app.route('/game/<int:game_id>/status', methods=['GET'])
def game_status_api(game_id):
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    game.update_active_game()
    pool, bonus_text = game.update_pool_and_bonus()
    formatted_called = [game.format_number(n) for n in game.called_numbers]
    
    taken_cartelas = []
    for cards in game.players.values():
        for c in cards:
            taken_cartelas.append(c.get('cartela_number'))

    # Auto-record game history and credit winners if game finished automatically
    if (game.status in ['finished', 'completed'] or game.winners) and not getattr(game, '_history_recorded', False):
        game._history_recorded = True
        prize_per_winner = round(pool / max(len(game.winners), 1), 2) if game.winners else 0.0
        
        for winner_info in game.winners:
            w_tid = winner_info.get('user_id')
            w_user = User.query.filter_by(telegram_id=w_tid).first()
            if w_user:
                if game.entry_price > 0:
                    w_user.balance += prize_per_winner
                w_user.games_won = (w_user.games_won or 0) + 1
                
                try:
                    hist = GameHistory(
                        game_id=game_id,
                        game_unique_code=getattr(game, 'unique_code', str(game_id)),
                        winner_id=w_user.id,
                        winner_name=w_user.username or "Player",
                        winning_cartela=winner_info.get('cartela_number', 1),
                        winning_board_data=json.dumps(winner_info),
                        total_calls=len(game.called_numbers),
                        called_numbers_str=",".join([game.format_number(n) for n in game.called_numbers]),
                        prize_amount=prize_per_winner
                    )
                    db.session.add(hist)
                    if game.entry_price > 0:
                        tx = Transaction(
                            user_id=w_user.id,
                            type='win',
                            amount=prize_per_winner,
                            status='completed'
                        )
                        db.session.add(tx)
                except Exception as e:
                    logger.exception(f"Error auto-recording history: {e}")

        for p_tid in game.players.keys():
            p_user = User.query.filter_by(telegram_id=p_tid).first()
            if p_user:
                p_user.games_played = (p_user.games_played or 0) + 1
        db.session.commit()

    return jsonify({
        'game_id': game.game_id,
        'unique_code': getattr(game, 'unique_code', str(game_id)),
        'active_players': len(game.players),
        'total_cards': game.get_total_cards(),
        'pool': round(pool, 2),
        'bonus': bonus_text,
        'status': game.status,
        'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 0,
        'called_numbers': formatted_called,
        'current_call': formatted_called[-1] if formatted_called else '---',
        'winners': game.winners,
        'prize_per_winner': round(pool / max(len(game.winners), 1), 2) if game.winners else 0.0,
        'taken_cartelas': taken_cartelas
    })

@app.route('/game/<int:game_id>/mark', methods=['POST'])
def mark_number(game_id):
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    card_index = int(data.get('card_index', 0))
    check_win = data.get('check_win', False)

    if check_win:
        pool, bonus_text = game.update_pool_and_bonus()
        winner, message, prize_per_winner = game.claim_bingo(user.telegram_id, card_index)
        
        if winner:
            if prize_per_winner <= 0 and pool > 0:
                prize_per_winner = pool / max(len(game.winners), 1)
            
            if game.entry_price > 0:
                user.balance += prize_per_winner

            user.games_won = (user.games_won or 0) + 1
            
            for p_tid in game.players.keys():
                p_user = User.query.filter_by(telegram_id=p_tid).first()
                if p_user:
                    p_user.games_played = (p_user.games_played or 0) + 1

            try:
                hist = GameHistory(
                    game_id=game_id,
                    game_unique_code=getattr(game, 'unique_code', str(game_id)),
                    winner_id=user.id,
                    winner_name=user.username or "Player",
                    winning_cartela=game.players[user.telegram_id][card_index]['cartela_number'],
                    winning_board_data=json.dumps(game.players[user.telegram_id][card_index]),
                    total_calls=len(game.called_numbers),
                    called_numbers_str=",".join([game.format_number(n) for n in game.called_numbers]),
                    prize_amount=prize_per_winner
                )
                db.session.add(hist)
                
                if game.entry_price > 0:
                    tx = Transaction(
                        user_id=user.id,
                        type='win',
                        amount=prize_per_winner,
                        status='completed'
                    )
                    db.session.add(tx)
                
                db.session.commit()
            except Exception as e:
                logger.exception(f"Error recording win history: {e}")
                db.session.rollback()

        return jsonify({
            'winner': winner,
            'message': message,
            'prize_per_winner': prize_per_winner,
            'winners': game.winners
        })

    return jsonify({'error': 'Invalid action'}), 400

@app.route('/game/<int:game_id>/leave', methods=['POST'])
def leave_game(game_id):
    try:
        if game_id in active_games:
            game = active_games[game_id]
            user_id = session.get('user_id')
            if user_id:
                game.player_leave(user_id)
        session.pop('active_game_id', None)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/deposit', methods=['POST'])
def deposit():
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    amount = float(data.get('amount', 0))
    payment_method = data.get('payment_method', 'telebirr')
    transaction_id = data.get('transaction_id', '')

    if amount < 10:
        return jsonify({'error': 'Minimum deposit amount is 10 ETB.'}), 400

    user.balance += amount
    tx = Transaction(
        user_id=user.id, 
        type='deposit', 
        amount=amount, 
        payment_method=payment_method,
        transaction_id=transaction_id,
        status='completed'
    )
    db.session.add(tx)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Deposit successful!'})

@app.route('/withdraw', methods=['POST'])
def withdraw():
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    amount = float(data.get('amount', 0))
    payment_method = data.get('payment_method', 'telebirr')
    withdrawal_phone = data.get('withdrawal_phone', '')

    if user.balance < amount:
        return jsonify({'error': 'Insufficient main balance.'}), 400

    user.balance -= amount
    tx = Transaction(
        user_id=user.id, 
        type='withdraw', 
        amount=amount, 
        payment_method=payment_method,
        withdrawal_phone=withdrawal_phone,
        status='pending'
    )
    db.session.add(tx)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Withdrawal request submitted successfully.'})

@app.route('/transfer', methods=['POST'])
def transfer_balance():
    sender_id = session.get('user_id')
    sender = User.query.filter_by(telegram_id=sender_id).first()
    if not sender:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    recipient_phone = data.get('phone')
    amount = float(data.get('amount', 0))

    if amount <= 0 or sender.balance < amount:
        return jsonify({'error': 'Invalid amount or insufficient balance.'}), 400

    recipient = User.query.filter_by(phone=recipient_phone).first()
    if not recipient or recipient.id == sender.id:
        return jsonify({'error': 'Recipient not found with this phone number.'}), 404

    sender.balance -= amount
    recipient.balance += amount

    transfer_record = Transfer(sender_id=sender.id, receiver_id=recipient.id, amount=amount)
    db.session.add(transfer_record)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Transfer successful!'})

# ==========================================
# ADMIN ROUTES (Fixed 500 Error & English)
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
        
        try:
            admin = Admin.query.filter_by(username=username).first()
            if admin and hashlib.sha256(password.encode()).hexdigest() == admin.password_hash:
                session['admin_logged_in'] = True
                session['is_super_admin'] = admin.is_super
                return redirect(url_for('admin_dashboard'))
        except Exception:
            pass
            
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['is_super_admin'] = True
            return redirect(url_for('admin_dashboard'))
            
        flash('Invalid username or password!')
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    games_list = list(active_games.values())
    active_count = len([g for g in games_list if hasattr(g, 'status') and g.status in ["active", "countdown", "playing"]])
    
    return render_template('admin/dashboard.html', 
                           games=games_list,
                           users=User.query.all(),
                           admins=Admin.query.all(),
                           total_players=User.query.count(),
                           active_games=active_count,
                           pending_withdrawals=Transaction.query.filter_by(type='withdraw', status='pending').all(),
                           transactions=Transaction.query.order_by(Transaction.id.desc()).limit(20).all())

@app.route('/admin/staff/add', methods=['POST'])
@admin_required
def admin_add_staff():
    if not session.get('is_super_admin'):
        flash('Only super admin can add staff!', 'error')
        return redirect(url_for('admin_dashboard'))
        
    username = request.form.get('username')
    password = request.form.get('password')
    
    existing = Admin.query.filter_by(username=username).first()
    if existing:
        flash('Username already exists!', 'error')
    else:
        new_admin = Admin(
            username=username,
            password_hash=hashlib.sha256(password.encode()).hexdigest(),
            is_super=False
        )
        db.session.add(new_admin)
        db.session.commit()
        flash('New staff added successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/staff/delete/<int:admin_id>', methods=['POST'])
@admin_required
def admin_delete_staff(admin_id):
    if not session.get('is_super_admin'):
        flash('Unauthorized action!', 'error')
        return redirect(url_for('admin_dashboard'))
        
    adm = Admin.query.get_or_404(admin_id)
    db.session.delete(adm)
    db.session.commit()
    flash('Staff deleted successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<int:user_id>/details')
@admin_required
def admin_user_details(user_id):
    user = User.query.get_or_404(user_id)
    user_txs = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id.desc()).all()
    return render_template('admin/user_details.html', user=user, transactions=user_txs)

@app.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def admin_approve_withdrawal(tx_id):
    tx = Transaction.query.get_or_404(tx_id)
    if tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Withdrawal approved successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/withdrawal/<int:tx_id>/reject', methods=['POST'])
@admin_required
def admin_reject_withdrawal(tx_id):
    tx = Transaction.query.get_or_404(tx_id)
    if tx.status == 'pending':
        tx.status = 'rejected'
        user = User.query.get(tx.user_id)
        if user:
            user.balance += abs(tx.amount)
        db.session.commit()
        flash('Withdrawal rejected and amount refunded.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('is_super_admin', None)
    return redirect(url_for('admin_login'))

@app.route('/ping')
def ping():
    return "Bot and Web are alive!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)