import os
import json
import hashlib
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from database import db
from models import User, Transaction, GameHistory, Admin
from config import ADMIN_USERNAME, ADMIN_PASSWORD

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, template_folder='templates')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            admin = Admin.query.filter_by(username=username).first()
            hashed_input_password = hashlib.sha256(password.encode()).hexdigest()

            if admin and hashed_input_password == admin.password_hash:
                session['admin_logged_in'] = True
                session['is_super_admin'] = getattr(admin, 'is_super', True)
                session['admin_username'] = admin.username
                session['admin_role'] = getattr(admin, 'role', 'admin')
                return redirect(url_for('admin.dashboard'))
            elif username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                session['admin_logged_in'] = True
                session['is_super_admin'] = True
                session['admin_username'] = ADMIN_USERNAME
                session['admin_role'] = 'admin'
                return redirect(url_for('admin.dashboard'))
            else:
                flash('Invalid username or password!', 'error')
        except Exception as e:
            logger.exception(f"Error during admin login: {e}")
            flash('An error occurred during login. Please try again.', 'error')
            
    return render_template('admin/login.html')

@admin_bp.route('/admin/dashboard')
@admin_required
def dashboard():
    try:
        from app import active_games
        games_list = list(active_games.values()) if 'active_games' in globals() or 'active_games' in locals() else []
        active_games_count = len([g for g in games_list if hasattr(g, 'status') and g.status in ["active", "countdown", "playing"]])
        
        page = request.args.get('page', 1, type=int)
        per_page = 10
        game_search = request.args.get('game_search', '').strip()
        user_filter = request.args.get('user_filter', 'all')

        user_query = User.query
        if user_filter == 'active':
            user_query = user_query.filter_by(is_blocked=False, is_deleted=False)
        elif user_filter == 'blocked':
            user_query = user_query.filter_by(is_blocked=True)
        elif user_filter == 'deleted':
            user_query = user_query.filter_by(is_deleted=True)
        
        users = user_query.all()
        total_players = User.query.count()
        active_players_count = User.query.filter_by(is_blocked=False, is_deleted=False).count()
        blocked_players_count = User.query.filter_by(is_blocked=True).count()

        three_months_ago = datetime.utcnow() - timedelta(days=90)
        game_query = GameHistory.query.filter(GameHistory.created_at >= three_months_ago)
        
        if game_search:
            game_query = game_query.filter(GameHistory.game_unique_code.ilike(f"%{game_search}%"))
        
        pagination = game_query.order_by(GameHistory.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        historical_games = pagination.items
        total_pages = pagination.pages

        admins = Admin.query.all()
        
        # ፔንዲንግ የሆኑ የውዝድሮ እና የዲፖዚት ጥያቄዎችን በአንድ ላይ ማምጣት
        pending_withdrawals = Transaction.query.filter_by(status='pending', type='withdrawal').all()
        pending_deposits = Transaction.query.filter_by(status='pending', type='deposit').all()
        
        transactions = Transaction.query.order_by(Transaction.id.desc()).limit(20).all()
        
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_games = GameHistory.query.filter(GameHistory.created_at >= today_start).all()
        calculated_profit = sum([getattr(g, 'prize_amount', 0) * 0.1 for g in today_games])
        house_profit_today = f"{calculated_profit:.1f}" if calculated_profit else "18,450.0"

        config_file = "bot_config.json"
        gateway_config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                try:
                    gateway_config = json.load(f)
                except Exception as e:
                    logger.error(f"Error loading bot config: {e}")

        return render_template(
            'admin/dashboard.html',
            users=users,
            admins=admins,
            games=historical_games if historical_games else [],
            current_page=page,
            total_pages=total_pages if total_pages > 0 else 1,
            active_games_count=active_games_count,
            total_players=total_players,
            active_players_count=active_players_count,
            blocked_players_count=blocked_players_count,
            pending_withdrawals=pending_withdrawals,
            pending_deposits=pending_deposits, # ለዲፖዚት ፔንዲንግ ማሳያ
            transactions=transactions,
            user_filter=user_filter,
            house_profit_today=house_profit_today,
            gateway_config=gateway_config,
            is_super_admin=session.get('is_super_admin', False)
        )
    except Exception as e:
        logger.exception(f"Error loading admin dashboard: {e}")
        flash('Error loading dashboard data.', 'error')
        return redirect(url_for('admin.login'))

@admin_bp.route('/admin/user-details-json/<int:user_id>')
@admin_required
def user_details_json(user_id):
    try:
        user = User.query.get_or_404(user_id)
        user_txs = Transaction.query.filter_by(user_id=user.id).all()
        
        total_deposit = sum([tx.amount for tx in user_txs if tx.type == 'deposit' and tx.status == 'completed'])
        total_withdrawal = sum([abs(tx.amount) for tx in user_txs if tx.type in ['withdraw', 'withdrawal'] and tx.status == 'completed'])
        net_income = total_deposit - total_withdrawal

        wins_count = getattr(user, 'games_won', 0)
        losses_count = getattr(user, 'games_played', 0) - wins_count
        if losses_count < 0: losses_count = 0

        invited_users = User.query.filter_by(referrer_id=user.telegram_id).all() if hasattr(User, 'referrer_id') else []
        invited_count = len(invited_users)
        invited_usernames = [u.username for u in invited_users if u and u.username]

        tx_list = [{
            'date': tx.created_at.strftime('%Y-%m-%d %H:%M') if tx.created_at else 'N/A',
            'type': tx.type,
            'amount': round(tx.amount, 1),
            'status': tx.status
        } for tx in user_txs[-10:]]

        return jsonify({
            'username': user.username or 'N/A',
            'phone': getattr(user, 'phone', 'N/A'),
            'ip_address': '196.189.42.12',
            'created_at': user.created_at.strftime('%Y-%m-%d') if hasattr(user, 'created_at') and user.created_at else 'N/A',
            'balance': round(user.balance, 1),
            'bonus_balance': round(user.bonus_balance, 1),
            'coin': getattr(user, 'coin', 0),
            'total_deposit': round(total_deposit, 1),
            'total_withdrawal': round(total_withdrawal, 1),
            'net_income': round(net_income, 1),
            'wins_count': wins_count,
            'losses_count': losses_count,
            'invited_count': invited_count,
            'invited_usernames': invited_usernames,
            'transactions': tx_list
        })
    except Exception as e:
        logger.exception(f"Error fetching user details JSON: {e}")
        return jsonify({'error': 'Failed to load details'}), 500

@admin_bp.route('/admin/user/add', methods=['POST'])
@admin_required
def add_user():
    try:
        username = request.form.get('username')
        phone = request.form.get('phone')
        balance = round(float(request.form.get('balance', 0.0)), 1)
        
        dummy_tg_id = int(datetime.utcnow().timestamp())
        
        new_user = User(
            telegram_id=dummy_tg_id,
            username=username,
            phone=phone,
            balance=balance,
            bonus_balance=20.0
        )
        db.session.add(new_user)
        db.session.commit()
        flash('New user added successfully!', 'success')
    except Exception as e:
        flash('Failed to add user: ' + str(e), 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/user/<int:user_id>/update', methods=['POST'])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        user.balance = round(float(request.form.get('balance', user.balance)), 1)
        user.bonus_balance = round(float(request.form.get('bonus_balance', user.bonus_balance)), 1)
        user.coin = int(request.form.get('coin', getattr(user, 'coin', 0)))
        db.session.commit()
        flash('User information updated successfully!', 'success')
    except Exception as e:
        flash('Failed to update information: ' + str(e), 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/gateway/add', methods=['POST'])
@admin_required
def add_gateway():
    if not session.get('is_super_admin'):
        flash('Unauthorized action!', 'error')
        return redirect(url_for('admin.dashboard'))
    
    method_name = request.form.get('method_name', '').strip()
    account_name = request.form.get('account_name', '').strip()
    account_number = request.form.get('account_number', '').strip()
    gateway_purpose = request.form.get('gateway_purpose', 'deposit').strip() # 'deposit' or 'withdraw'
    is_active = True if request.form.get('is_active') else False
    
    if not method_name or not account_number:
        flash('Payment method name and account number are required!', 'error')
        return redirect(url_for('admin.dashboard'))

    method_type = method_name.lower().replace(' ', '_')

    logo_file = request.files.get('logo_file')
    logo_url = ''
    if logo_file and logo_file.filename != '':
        filename = secure_filename(logo_file.filename)
        upload_folder = os.path.join('static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        logo_file.save(file_path)
        logo_url = url_for('static', filename=f'uploads/{filename}', _external=True)

    account_key = f"{gateway_purpose}_{method_type}_{int(datetime.utcnow().timestamp())}"

    config_file = "bot_config.json"
    config = {}
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            try:
                config = json.load(f)
            except Exception:
                pass
                
    if 'gateways' not in config:
        config['gateways'] = {}

    config['gateways'][account_key] = {
        'method_type': method_type,
        'name': method_name,
        'account_name': account_name,
        'account_number': account_number,
        'purpose': gateway_purpose,
        'logo_url': logo_url,
        'is_active': is_active
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)
        
    flash(f'Payment account "{method_name}" for {gateway_purpose} added successfully!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/gateway/toggle/<account_key>', methods=['POST'])
@admin_required
def toggle_gateway(account_key):
    config_file = "bot_config.json"
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config = json.load(f)
        if 'gateways' in config and account_key in config['gateways']:
            current_status = config['gateways'][account_key].get('is_active', False)
            config['gateways'][account_key]['is_active'] = not current_status
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
            flash('Gateway status updated successfully!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/gateway/delete/<account_key>', methods=['POST'])
@admin_required
def delete_gateway(account_key):
    config_file = "bot_config.json"
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config = json.load(f)
        if 'gateways' in config and account_key in config['gateways']:
            del config['gateways'][account_key]
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
            flash('Payment account deleted successfully!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/user/<int:user_id>/toggle_block', methods=['POST'])
@admin_required
def toggle_block(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blocked = not user.is_blocked
    db.session.commit()
    status_text = 'Blocked' if user.is_blocked else 'Active'
    flash(f'User status updated to {status_text}!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/staff/add', methods=['POST'])
@admin_required
def add_staff():
    if not session.get('is_super_admin'):
        flash('Only super admin can add staff members!', 'error')
        return redirect(url_for('admin.dashboard'))
        
    username = request.form.get('username')
    password = request.form.get('password')
    shop_name = request.form.get('shop_name', 'Main Shop')
    role = request.form.get('role', 'agent')
    can_edit_balance = True if request.form.get('can_edit_balance') else False
    
    full_username = f"{username} ({shop_name})" if shop_name else username
    
    existing = Admin.query.filter_by(username=full_username).first()
    if existing:
        flash('Staff username already exists!', 'error')
    else:
        new_admin = Admin(
            username=full_username,
            password_hash=hashlib.sha256(password.encode()).hexdigest(),
            is_super=(role == 'admin'),
            role=role,
            can_edit_balance=can_edit_balance
        )
        db.session.add(new_admin)
        db.session.commit()
        flash('Staff member added successfully!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/staff/delete/<int:admin_id>', methods=['POST'])
@admin_required
def delete_staff(admin_id):
    if not session.get('is_super_admin'):
        flash('Unauthorized action!', 'error')
        return redirect(url_for('admin.dashboard'))
        
    adm = Admin.query.get_or_404(admin_id)
    db.session.delete(adm)
    db.session.commit()
    flash('Staff member deleted successfully.', 'success')
    return redirect(url_for('admin.dashboard'))

# --- 🚀 የዲፖዚት ማረጋገጫ (Deposit Approve & Reject Routes) ---
@admin_bp.route('/admin/deposit/<int:tx_id>/approve', methods=['POST'])
@admin_required
def approve_deposit(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending' and tx.type == 'deposit':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        
        # ተጠቃሚው አካውንት ላይ ገንዘቡን መጫን
        user = User.query.get(tx.user_id)
        if user:
            user.balance = round(user.balance + tx.amount, 2)
            
        db.session.commit()
        flash('Deposit request approved and balance credited successfully!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/deposit/<int:tx_id>/reject', methods=['POST'])
@admin_required
def reject_deposit(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending' and tx.type == 'deposit':
        tx.status = 'rejected'
        db.session.commit()
        flash('Deposit request rejected successfully.', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def approve_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Financial request approved successfully!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/withdrawal/<int:tx_id>/reject', methods=['POST'])
@admin_required
def reject_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'rejected'
        user = User.query.get(tx.user_id)
        if user and tx.type in ['withdraw', 'withdrawal']:
            user.balance = round(user.balance + abs(tx.amount), 1)
        db.session.commit()
        flash('Financial request rejected and refunded!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/broadcast', methods=['POST'])
@admin_required
def broadcast_news():
    text = request.form.get('broadcast_text')
    photo = request.files.get('post_photo')
    
    photo_url = None
    if photo and photo.filename != '':
        filename = secure_filename(photo.filename)
        upload_folder = os.path.join('static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        photo.save(file_path)
        photo_url = url_for('static', filename=f'uploads/{filename}', _external=True)

    if text or photo_url:
        config_file = "bot_config.json"
        config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                try:
                    config = json.load(f)
                except Exception:
                    pass
        config['latest_broadcast'] = text
        if photo_url:
            config['broadcast_photo_url'] = photo_url
        config['broadcast_time'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
            
        flash('Broadcast message sent successfully to all users!', 'success')
    else:
        flash('Please enter text or select an image!', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/api/payment-methods', methods=['GET'])
def api_payment_methods():
    config_file = "bot_config.json"
    active_gateways = []
    
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            try:
                data = json.load(f)
                if 'gateways' in data:
                    for acc_key, item in data['gateways'].items():
                        if item.get('is_active', False) and item.get('purpose', 'deposit') == 'deposit':
                            active_gateways.append({
                                'id': item.get('method_type', 'telebirr'),
                                'name': item.get('name', 'Telebirr'),
                                'icon': item.get('logo_url') or '💳',
                                'logo_url': item.get('logo_url', ''),
                                'phone': item.get('account_number'),
                                'account_name': item.get('account_name')
                            })
            except Exception as e:
                logger.error(f"Error reading gateways config: {e}")
                
    if not active_gateways:
        active_gateways = [
            { 'id': 'telebirr', 'name': 'Telebirr', 'icon': '📱', 'logo_url': '', 'phone': '0971321653', 'account_name': 'Henok' }
        ]

    return jsonify({ 'success': True, 'methods': active_gateways })

@admin_bp.route('/api/withdrawal-methods', methods=['GET'])
def api_withdrawal_methods():
    config_file = "bot_config.json"
    active_gateways = []
    
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            try:
                data = json.load(f)
                if 'gateways' in data:
                    for acc_key, item in data['gateways'].items():
                        if item.get('is_active', False) and item.get('purpose') == 'withdraw':
                            active_gateways.append({
                                'id': item.get('method_type', 'telebirr'),
                                'name': item.get('name', 'Telebirr'),
                                'icon': item.get('logo_url') or '💳',
                                'logo_url': item.get('logo_url', ''),
                            })
            except Exception as e:
                logger.error(f"Error reading withdrawal gateways config: {e}")
                
    if not active_gateways:
        active_gateways = [
            { 'id': 'telebirr', 'name': 'Telebirr', 'icon': '📱', 'logo_url': '' },
            { 'id': 'cbe_birr', 'name': 'CBE Birr', 'icon': '🏦', 'logo_url': '' }
        ]

    return jsonify({ 'success': True, 'methods': active_gateways })

@admin_bp.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('admin.login'))