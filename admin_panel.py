import os
import json
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime
from werkzeug.utils import secure_filename
from database import db
from models import User, Transaction, GameHistory, Admin
from config import ADMIN_USERNAME, ADMIN_PASSWORD

# Admin Blueprint creation
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
        
        # Verify from Admin model or config
        admin = Admin.query.filter_by(username=username).first()
        if admin and hashlib.sha256(password.encode()).hexdigest() == admin.password_hash:
            session['admin_logged_in'] = True
            session['is_super_admin'] = admin.is_super
            session['admin_username'] = admin.username
            return redirect(url_for('admin.dashboard'))
        elif username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['is_super_admin'] = True
            session['admin_username'] = ADMIN_USERNAME
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid username or password!', 'error')
            
    return render_template('admin/login.html')

@admin_bp.route('/admin/dashboard')
@admin_required
def dashboard():
    from app import active_games
    games_list = list(active_games.values())
    active_count = len([g for g in games_list if hasattr(g, 'status') and g.status in ["active", "countdown"]])
    
    users = User.query.all()
    admins = Admin.query.all()
    pending_withdrawals = Transaction.query.filter_by(type='withdraw', status='pending').all()
    transactions = Transaction.query.order_by(Transaction.id.desc()).limit(20).all()
    
    return render_template(
        'admin/dashboard.html',
        users=users,
        admins=admins,
        games=games_list,
        active_games=active_count,
        total_players=len(users),
        pending_withdrawals=pending_withdrawals,
        transactions=transactions,
        is_super_admin=session.get('is_super_admin', False)
    )

# View user details and transactions
@admin_bp.route('/admin/user/<int:user_id>/details')
@admin_required
def user_details(user_id):
    user = User.query.get_or_404(user_id)
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id.desc()).all()
    return render_template('admin/user_details.html', user=user, transactions=transactions)

# Update user balance, bonus, and coins
@admin_bp.route('/admin/user/<int:user_id>/update', methods=['POST'])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        user.balance = float(request.form.get('balance', user.balance))
        user.bonus_balance = float(request.form.get('bonus_balance', user.bonus_balance))
        user.coin = int(request.form.get('coin', user.coin))
        db.session.commit()
        flash('User information updated successfully!', 'success')
    except Exception as e:
        flash('Failed to update information: ' + str(e), 'error')
    return redirect(url_for('admin.dashboard'))

# Block or Unblock user
@admin_bp.route('/admin/user/<int:user_id>/toggle_block', methods=['POST'])
@admin_required
def toggle_block(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blocked = not user.is_blocked
    db.session.commit()
    status_text = 'Blocked' if user.is_blocked else 'Active'
    flash(f'User is now {status_text}!', 'success')
    return redirect(url_for('admin.dashboard'))

# Add admin or agent by role (Superadmin only)
@admin_bp.route('/admin/staff/add', methods=['POST'])
@admin_required
def add_staff():
    if not session.get('is_super_admin'):
        flash('Only super admin can add staff!', 'error')
        return redirect(url_for('admin.dashboard'))
        
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'agent')
    
    existing = Admin.query.filter_by(username=username).first()
    if existing:
        flash('Username already exists!', 'error')
    else:
        new_admin = Admin(
            username=username,
            password_hash=hashlib.sha256(password.encode()).hexdigest(),
            is_super=(role == 'admin')
        )
        db.session.add(new_admin)
        db.session.commit()
        flash(f'New {role} added successfully!', 'success')
    return redirect(url_for('admin.dashboard'))

# Delete staff member
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

# Delete data (user or transaction)
@admin_bp.route('/admin/delete/<string:data_type>/<int:item_id>', methods=['POST'])
@admin_required
def delete_data(data_type, item_id):
    if data_type == 'user':
        item = User.query.get_or_404(item_id)
        db.session.delete(item)
        flash('User deleted successfully.', 'success')
    elif data_type == 'transaction':
        item = Transaction.query.get_or_404(item_id)
        db.session.delete(item)
        flash('Transaction deleted successfully.', 'success')
    db.session.commit()
    return redirect(url_for('admin.dashboard'))

# Approve withdrawal request
@admin_bp.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def approve_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Withdrawal request approved (Completed)!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

# Reject withdrawal request and refund amount
@admin_bp.route('/admin/withdrawal/<int:tx_id>/reject', methods=['POST'])
@admin_required
def reject_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'rejected'
        user = User.query.get(tx.user_id)
        if user:
            user.balance += abs(tx.amount)
        db.session.commit()
        flash('Withdrawal request rejected and amount refunded to user balance!', 'success')
    else:
        flash('Transaction not found or already processed.', 'error')
    return redirect(url_for('admin.dashboard'))

# Broadcast news to bot
@admin_bp.route('/admin/broadcast', methods=['POST'])
@admin_required
def broadcast_news():
    text = request.form.get('broadcast_text')
    if text:
        config_file = "bot_config.json"
        config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                try:
                    config = json.load(f)
                except:
                    pass
        config['latest_broadcast'] = text
        config['broadcast_time'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        with open(config_file, 'w') as f:
            json.dump(config, f)
        flash('Broadcast news posted and updated on bot automatically!', 'success')
    else:
        flash('Please enter broadcast message text!', 'error')
    return redirect(url_for('admin.dashboard'))

# Update welcome image (Upload file or URL)
@admin_bp.route('/admin/settings/image', methods=['POST'])
@admin_required
def update_welcome_image():
    config_file = "bot_config.json"
    config = {}
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            try:
                config = json.load(f)
            except:
                pass

    if 'welcome_image' in request.files:
        file = request.files['welcome_image']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            upload_folder = os.path.join('static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            
            image_url = url_for('static', filename=f'uploads/{filename}', _external=True)
            config['welcome_image_url'] = image_url
            with open(config_file, 'w') as f:
                json.dump(config, f)
            flash('Welcome image uploaded from device and updated successfully!', 'success')
            return redirect(url_for('admin.dashboard'))
            
    image_url = request.form.get('image_url')
    if image_url:
        config['welcome_image_url'] = image_url
        with open(config_file, 'w') as f:
            json.dump(config, f)
        flash('Welcome image URL updated successfully!', 'success')
    else:
        flash('Please select an image file or enter a valid URL!', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    session.pop('is_super_admin', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin.login'))