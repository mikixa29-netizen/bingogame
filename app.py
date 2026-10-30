import os
import random
import json
import logging
import hashlib
import re
import requests
from flask import Flask, jsonify, request, session, render_template, redirect, url_for, flash
from datetime import datetime, date, timedelta
from database import db, init_db
from game_logic import BingoGame
from config import ADMIN_USERNAME, ADMIN_PASSWORD
from admin_panel import admin_bp

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

init_db(app)
app.register_blueprint(admin_bp)

from models import User, Game, GameParticipant, Transaction, Transfer, GameHistory, Admin, PaymentGateway

with app.app_context():
    db.create_all()
    try:
        db.session.execute(db.text("ALTER TABLE game_history ADD COLUMN IF NOT EXISTS is_win BOOLEAN DEFAULT FALSE;"))
        db.session.execute(db.text("ALTER TABLE game_history ADD COLUMN IF NOT EXISTS user_id BIGINT;"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.info(f"Migration note: {e}")

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

def init_default_games():
    if not active_games:
        active_games[1] = BingoGame(1, entry_price=10, max_cards_per_player=4)
        active_games[2] = BingoGame(2, entry_price=20, max_cards_per_player=4)
        active_games[3] = BingoGame(3, entry_price=50, max_cards_per_player=4)
        active_games[4] = BingoGame(4, entry_price=100, max_cards_per_player=4)
        active_games[999] = BingoGame(999, entry_price=0, max_cards_per_player=5)

init_default_games()

@app.route('/')
def index():
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return "Please open this game through the Telegram Bot (@EdilBingoBot).[cite: 3]", 403
    
    user_id = int(user_id)
    session['user_id'] = user_id
    
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return "User not registered. Please start the Telegram bot first.[cite: 3]", 403
        
    if user.is_blocked:
        return "Your account has been blocked by the administrator.[cite: 3]", 403

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
    ).join(GameHistory, User.id == GameHistory.winner_id).filter(GameHistory.is_win == True)
    
    if timeframe == 'today':
        start_date = datetime(now.year, now.month, now.day)
        query = query.filter(GameHistory.finished_at >= start_date)
    elif timeframe == 'week':
        start_date = now - timedelta(days=7)
        query = query.filter(GameHistory.finished_at >= start_date)
    elif timeframe == 'month':
        start_date = datetime(now.year, now.month, 1)
        query = query.filter(GameHistory.finished_at >= start_date)
        
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
    
    game_history = GameHistory.query.filter_by(user_id=user.id).order_by(GameHistory.id.desc()).limit(30).all()
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
            derash_amount = game.get_derash_amount() if hasattr(game, 'get_derash_amount') else pool
            jackpot_current = game.get_current_jackpot() if hasattr(game, 'get_current_jackpot') else 0.0

            games_data.append({
                'id': g_id,
                'unique_code': getattr(game, 'unique_code', str(g_id)),
                'players_count': len(game.players),
                'total_cards': game.get_total_cards(),
                'entry_price': game.entry_price,
                'status': game.status,
                'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 30,
                'pool': round(pool, 2),
                'derash': round(derash_amount, 2),
                'jackpot_pool': round(jackpot_current, 2),
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

        for ag_id, ag in active_games.items():
            if ag.entry_price == entry_price and ag.status in ['countdown', 'active'] and user.telegram_id in ag.players and len(ag.players[user.telegram_id]) > 0:
                return jsonify({
                    'success': True,
                    'game_id': ag_id,
                    'entry_price': entry_price,
                    'has_cartela': True
                })

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

    if game.status in ['active', 'playing'] and user.telegram_id in game.players and len(game.players[user.telegram_id]) > 0:
        return redirect(url_for('play_game', game_id=g_id))

    if game.status == 'finished':
        entry_price = game.entry_price
        waiting_game = next((g for g in active_games.values() if g.entry_price == entry_price and g.status in ['waiting', 'countdown']), None)
        if waiting_game:
            g_id = waiting_game.game_id
            game = waiting_game
        else:
            new_game_id = max(active_games.keys(), default=0) + 1
            if new_game_id == 999:
                new_game_id = 1000
            game = BingoGame(new_game_id, entry_price=entry_price, max_cards_per_player=5 if entry_price == 0 else 4)
            active_games[new_game_id] = game
            g_id = new_game_id

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
        game_code=game.unique_code,
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

    existing_cards_count = len(game.players.get(user.telegram_id, []))
    if existing_cards_count + len(cartela_numbers) > game.max_cards_per_player:
        return jsonify({'error': f'Maximum allowed cartelas is {game.max_cards_per_player}!'}), 400

    total_cost = game.entry_price * len(cartela_numbers)

    if game.entry_price > 0:
        total_user_balance = (user.balance or 0.0) + (user.bonus_balance or 0.0)
        if total_user_balance < total_cost:
            return jsonify({'error': 'Insufficient balance for selected cartelas!'}), 400

        bonus_bal = user.bonus_balance or 0.0
        main_bal = user.balance or 0.0

        if bonus_bal >= total_cost:
            user.bonus_balance -= total_cost
        else:
            remainder = total_cost - bonus_bal
            user.bonus_balance = 0.0
            user.balance = main_bal - remainder

    username = user.username or "Player"
    for c_num in cartela_numbers:
        success, msg, board = game.add_player_card(user.telegram_id, username=username, cartela_number=c_num)
        if not success:
            return jsonify({'error': msg}), 400

    db.session.commit()
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
    derash_amount = game.get_derash_amount() if hasattr(game, 'get_derash_amount') else pool

    return render_template('game.html',
                           game_id=game_id,
                           game_code=game.unique_code,
                           game=game,
                           player_cards=player_cards,
                           called_numbers=[game.format_number(n) for n in game.called_numbers],
                           active_players=len(game.players),
                           game_status=game.status,
                           entry_price=game.entry_price,
                           pool=round(derash_amount, 2),
                           bonus=bonus_text,
                           balance=user.balance)

@app.route('/game/<int:game_id>/status', methods=['GET'])
def game_status_api(game_id):
    if game_id not in active_games:
        return jsonify({'error': 'Game not found'}), 404

    game = active_games[game_id]
    game.update_active_game()
    pool, bonus_text = game.update_pool_and_bonus()
    derash_amount = game.get_derash_amount() if hasattr(game, 'get_derash_amount') else pool
    formatted_called = [game.format_number(n) for n in game.called_numbers]
    
    taken_cartelas = []
    for cards in game.players.values():
        for c in cards:
            taken_cartelas.append(c.get('cartela_number'))

    if (game.status in ['finished', 'completed'] or game.winners) and not getattr(game, '_history_recorded', False):
        game._history_recorded = True
        prize_per_winner = round(derash_amount / max(len(game.winners), 1), 2) if game.winners else 0.0
        winner_user_ids = [w.get('user_id') for w in game.winners]
        winner_names_str = ", ".join([w.get('username', 'Player') for w in game.winners]) if game.winners else "No Winner"

        winner_db_id = None
        if game.winners:
            w_tg_id = game.winners[0].get('user_id')
            w_user_obj = User.query.filter_by(telegram_id=w_tg_id).first()
            if w_user_obj:
                winner_db_id = w_user_obj.id

        for p_tid in game.players.keys():
            p_user = User.query.filter_by(telegram_id=p_tid).first()
            if p_user:
                p_user.games_played = (p_user.games_played or 0) + 1
                is_winner = p_tid in winner_user_ids
                
                if is_winner:
                    if game.entry_price > 0:
                        p_user.balance += prize_per_winner
                    p_user.games_won = (p_user.games_won or 0) + 1

                player_card_info = next((c for c in game.players.get(p_tid, []) if c.get('cartela_number') == next((w.get('cartela_number') for w in game.winners if w.get('user_id') == p_tid), c.get('cartela_number'))), game.players.get(p_tid, [{}])[0])

                try:
                    hist = GameHistory(
                        game_id=game_id,
                        game_unique_code=getattr(game, 'unique_code', str(game_id)),
                        user_id=p_user.id,
                        winner_id=winner_db_id,
                        winner_name=winner_names_str,
                        winning_cartela=player_card_info.get('cartela_number', 1),
                        winning_board_data=json.dumps(player_card_info),
                        total_calls=len(game.called_numbers),
                        called_numbers_str=",".join([game.format_number(n) for n in game.called_numbers]),
                        prize_amount=prize_per_winner if is_winner else 0.0,
                        is_win=is_winner
                    )
                    db.session.add(hist)
                    if is_winner and game.entry_price > 0:
                        tx = Transaction(
                            user_id=p_user.id,
                            type='win',
                            amount=prize_per_winner,
                            status='completed'
                        )
                        db.session.add(tx)
                except Exception as e:
                    logger.exception(f"Error auto-recording history: {e}")

        db.session.commit()

    return jsonify({
        'game_id': game.game_id,
        'unique_code': getattr(game, 'unique_code', str(game_id)),
        'active_players': len(game.players),
        'total_cards': game.get_total_cards(),
        'pool': round(derash_amount, 2),
        'bonus': bonus_text,
        'status': game.status,
        'countdown_remaining': game.get_remaining_countdown() if game.status == 'countdown' else 0,
        'called_numbers': formatted_called,
        'current_call': formatted_called[-1] if formatted_called else '---',
        'winners': game.winners,
        'prize_per_winner': round(derash_amount / max(len(game.winners), 1), 2) if game.winners else 0.0,
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
        derash_amount = game.get_derash_amount() if hasattr(game, 'get_derash_amount') else pool
        winner, message, prize_per_winner = game.claim_bingo(user.telegram_id, card_index)
        
        return jsonify({
            'winner': winner,
            'message': message,
            'prize_per_winner': prize_per_winner,
            'winners': game.winners
        })

    number = data.get('number')
    if number is not None:
        success = game.mark_number(user.telegram_id, card_index, int(number))
        return jsonify({'success': success, 'marked': success})

    return jsonify({'error': 'Invalid action'}), 400

@app.route('/game/<int:game_id>/leave', methods=['POST'])
def leave_game(game_id):
    try:
        if game_id in active_games:
            game = active_games[game_id]
            user_id = session.get('user_id')
            if user_id:
                user = User.query.filter_by(telegram_id=user_id).first()
                card_count = len(game.players.get(user_id, []))
                total_cost = game.entry_price * card_count

                success, msg, refund_allowed = game.player_leave(user_id)
                if success and refund_allowed and user and total_cost > 0:
                    user.balance += total_cost
                    db.session.commit()

        session.pop('active_game_id', None)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# --- 🚀 verify.et API Integration & Pending / Manual Admin Review Route ---
VERIFY_ET_API_KEY = os.getenv('VERIFY_ET_API_KEY', 'your_verify_et_api_key_here')
VERIFY_ET_URL = "https://verify.et/api/verify?waitMs=4000"

@app.route('/api/deposit/verify', methods=['POST'])
def verify_deposit():
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first() if user_id else None
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json or {}
    bank = str(data.get('bank', '')).strip().lower() # telebirr, cbe, cbebirr, mpesa
    reference = str(data.get('reference', '')).strip()
    phone = str(data.get('phone', '')).strip()
    user_entered_amount = float(data.get('amount', 0))

    if not bank or not reference or user_entered_amount <= 0:
        return jsonify({'success': False, 'message': 'እባክዎ ሁሉንም መረጃዎች በትክክል ይሙሉ!'}), 400

    # Duplicate Transaction Check
    existing_tx = Transaction.query.filter_by(transaction_id=reference).first()
    if existing_tx:
        return jsonify({'success': False, 'message': 'ይህ የትራንዛክሽን ሪፈረንስ ቁጥር ቀደም ሲል ጥቅም ላይ ውሏል!'}), 400

    # አድሚኑ ያስቀመጠውን ትክክለኛ የክፍያ መንገድ (Gateway) ከዳታቤዝ ማምጣት
    valid_gateway = PaymentGateway.query.filter(
        PaymentGateway.is_active == True,
        PaymentGateway.purpose == 'deposit',
        (PaymentGateway.name.ilike(f"%{bank}%")) | (PaymentGateway.id == bank if bank.isdigit() else False)
    ).first()

    expected_admin_account = valid_gateway.account_number if valid_gateway else ""

    # verify.et ፔይሎድ ማዘጋጀት
    payload = { "bank": bank }
    if bank in ['telebirr', 'mpesa']:
        payload["transactionNumber"] = reference
    elif bank == 'cbe':
        payload["reference"] = reference
    elif bank == 'cbebirr':
        payload["receiptNumber"] = reference
        if phone: payload["phone"] = phone
    else:
        payload["reference"] = reference

    headers = {
        "Content-Type": "application/json",
        "x-api-key": VERIFY_ET_API_KEY,
        "Idempotency-Key": f"edil-bingo-dep-{user.telegram_id}-{reference}"
    }

    try:
        response = requests.post(VERIFY_ET_URL, json=payload, headers=headers, timeout=10)
        result = response.json()
        status = result.get('status') # 'verified', 'pending', 'failed', 'not-found'

        if status == 'verified':
            tx_data = result.get('data', {})
            verified_amount = float(tx_data.get('amount', user_entered_amount))
            verified_receiver = str(tx_data.get('receiverPhone') or tx_data.get('receiverAccount', '')).strip()

            # ሎጂክ: አድሚኑ አካውንቱን ቀይሮ ከሆነ እና ተጠቃሚው በቀድሞው አካውንት ከላከ (Mismatch) -> ወደ Pending መላክ
            if expected_admin_account and verified_receiver and verified_receiver != expected_admin_account:
                pending_tx = Transaction(
                    user_id=user.id,
                    type='deposit',
                    amount=user_entered_amount,
                    payment_method=valid_gateway.name if valid_gateway else bank,
                    transaction_id=reference,
                    status='pending'
                )
                db.session.add(pending_tx)
                db.session.commit()
                return jsonify({
                    'success': True,
                    'status': 'pending',
                    'message': 'የተቀባዩ አካውንት የተለወጠ በመሆኑ ክፍያዎ ለዕይታ (Pending) ተመዝግቧል። አድሚኑ በማኑዋል ያረጋግጠዋል!'
                })

            # ሁሉም ነገር ትክክል ከሆነ -> ሒሳብ በራስ-ሰር መጫን (Completed)
            user.balance = round(user.balance + verified_amount, 2)
            new_tx = Transaction(
                user_id=user.id,
                type='deposit',
                amount=verified_amount,
                payment_method=valid_gateway.name if valid_gateway else bank,
                transaction_id=reference,
                status='completed'
            )
            db.session.add(new_tx)
            db.session.commit()

            return jsonify({
                'success': True,
                'status': 'completed',
                'message': f'ክፍያው በ verify.et ተረጋግጧል! {verified_amount} ብር አካውንትዎ ላይ ገብቷል።',
                'amount': verified_amount
            })
        else:
            # ፔንዲንግ ወይም ኖት ፋውንድ ከሆነ -> ወደ አድሚን ፔነል Pending አድርጎ መመዝገብ
            pending_tx = Transaction(
                user_id=user.id,
                type='deposit',
                amount=user_entered_amount,
                payment_method=valid_gateway.name if valid_gateway else bank,
                transaction_id=reference,
                status='pending'
            )
            db.session.add(pending_tx)
            db.session.commit()

            return jsonify({
                'success': True,
                'status': 'pending',
                'message': 'ክፍያው በራስ-ሰር አልተረጋገጠም። በ Pending መልክ ተመዝግቧል፣ አድሚኑ ማኑዋል ያረጋግጠዋል!'
            })

    except requests.exceptions.RequestException:
        # የኔትወርክ ወይም የሰርቨር ችግር ሲኖር Pending ማድረግ
        pending_tx = Transaction(
            user_id=user.id,
            type='deposit',
            amount=user_entered_amount,
            payment_method=bank,
            transaction_id=reference,
            status='pending'
        )
        db.session.add(pending_tx)
        db.session.commit()
        return jsonify({
            'success': True,
            'status': 'pending',
            'message': 'የሰርቨር መዘግየት አጋጥሟል። ክፍያዎ በ Pending ተመዝግቧል፣ አድሚኑ ያረጋግጠዋል።'
        })

@app.route('/api/payment-methods', methods=['GET'])
def api_payment_methods():
    gateways = PaymentGateway.query.filter_by(is_active=True, purpose='deposit').all()
    methods = []
    for g in gateways:
        methods.append({
            'id': str(g.name).lower().replace(' ', '_'),
            'name': g.name,
            'account_name': g.account_name,
            'phone': g.account_number,
            'logo_url': g.logo_url or ''
        })
    
    if not methods:
        methods = [{'id': 'telebirr', 'name': 'Telebirr', 'account_name': 'Henok', 'phone': '0971321653', 'logo_url': ''}]
    
    return jsonify({'success': True, 'methods': methods})

@app.route('/api/withdrawal-methods', methods=['GET'])
def api_withdrawal_methods():
    gateways = PaymentGateway.query.filter_by(is_active=True, purpose='withdraw').all()
    methods = []
    for g in gateways:
        methods.append({
            'id': str(g.id),
            'name': g.name,
            'logo_url': g.logo_url or ''
        })
        
    if not methods:
        methods = [
            {'id': 'telebirr', 'name': 'Telebirr', 'logo_url': ''},
            {'id': 'cbe_birr', 'name': 'CBE Birr', 'logo_url': ''}
        ]
        
    return jsonify({'success': True, 'methods': methods})

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
        type='withdrawal', 
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
    raw_phone = str(data.get('phone', '')).strip()
    amount = float(data.get('amount', 0))

    if amount < 10 or sender.bonus_balance < amount:
        return jsonify({'error': 'Invalid amount or insufficient bonus balance.'}), 400

    clean_phone = raw_phone.replace('+', '').replace(' ', '')
    recipient = User.query.filter(
        (User.phone == clean_phone) | 
        (User.phone == '0' + clean_phone[-9:]) | 
        (User.phone == '251' + clean_phone[-9:])
    ).first()

    if not recipient or recipient.id == sender.id:
        return jsonify({'error': 'Recipient not found with this phone number.'}), 404

    sender.bonus_balance -= amount
    recipient.bonus_balance += amount

    transfer_record = Transfer(sender_id=sender.id, receiver_id=recipient.id, amount=amount)
    tx_sender = Transaction(user_id=sender.id, type='transfer_out', amount=amount, payment_method='wallet', status='completed')
    tx_receiver = Transaction(user_id=recipient.id, type='transfer_in', amount=amount, payment_method='wallet', status='completed')
    
    db.session.add_all([transfer_record, tx_sender, tx_receiver])
    db.session.commit()

    return jsonify({'success': True, 'message': 'Balance transferred successfully!'})

@app.route('/wallet/transactions', methods=['GET'])
def get_user_transactions():
    user_id = session.get('user_id')
    user = User.query.filter_by(telegram_id=user_id).first()
    if not user:
        return jsonify({'transactions': []})

    timeframe = request.args.get('timeframe', 'today')
    tx_type = request.args.get('type', 'all')
    now = datetime.utcnow()

    query = Transaction.query.filter_by(user_id=user.id)

    if timeframe == 'today':
        start_date = datetime(now.year, now.month, now.day)
        query = query.filter(Transaction.created_at >= start_date)
    elif timeframe == 'week':
        start_date = now - timedelta(days=7)
        query = query.filter(Transaction.created_at >= start_date)
    elif timeframe == 'month':
        start_date = now - timedelta(days=30)
        query = query.filter(Transaction.created_at >= start_date)
    elif timeframe == '3months':
        start_date = now - timedelta(days=90)
        query = query.filter(Transaction.created_at >= start_date)

    if tx_type != 'all':
        if tx_type == 'transfer':
            query = query.filter(Transaction.type.in_(['transfer_in', 'transfer_out']))
        else:
            query = query.filter(Transaction.type == tx_type)

    results = query.order_by(Transaction.id.desc()).all()
    
    formatted_txs = []
    for t in results:
        formatted_txs.append({
            'id': t.id,
            'type': t.type,
            'amount': t.amount,
            'method': t.payment_method or 'telebirr',
            'status': t.status or 'completed',
            'date': t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else ''
        })

    return jsonify({'transactions': formatted_txs})

@app.route('/ping')
def ping():
    return "Bot and Web are alive!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)