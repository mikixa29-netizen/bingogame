import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime
from database import db
from models import User, Transaction, GameHistory
from config import ADMIN_USERNAME, ADMIN_PASSWORD

# አድሚን ብሉፕሪንት መፍጠር
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
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        else:
            flash('የተሳሳተ መግቢያ ስም ወይም የይለፍ ቃል!')
            
    return render_template('admin/login.html')

@admin_bp.route('/admin/dashboard')
@admin_required
def dashboard():
    # ከ ዋናው መተግበሪያ active_games መዝገብን መጥራት
    from app import active_games
    games_list = list(active_games.values())
    active_count = len([g for g in games_list if hasattr(g, 'status') and g.status in ["active", "countdown"]])
    
    users = User.query.all()
    pending_withdrawals = Transaction.query.filter_by(type='withdraw', status='pending').all()
    transactions = Transaction.query.order_by(Transaction.id.desc()).limit(20).all()
    
    return render_template(
        'admin/dashboard.html',
        users=users,
        games=games_list,
        active_games=active_count,
        total_players=len(users),
        pending_withdrawals=pending_withdrawals,
        transactions=transactions
    )

# የተጠቃሚን ዝርዝር ገቢ እና ወጪ ማየት (View Details)
@admin_bp.route('/admin/user/<int:user_id>/details')
@admin_required
def user_details(user_id):
    user = User.query.get_or_404(user_id)
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id.desc()).all()
    return render_template('admin/user_details.html', user=user, transactions=transactions)

# አድሚን ወይም አጀንት በሮል (Role) ማከል
@admin_bp.route('/admin/staff/add', methods=['POST'])
@admin_required
def add_staff():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'agent') # admin ወይም agent
    
    existing = User.query.filter_by(username=username).first()
    if existing:
        flash('ይህ ዩዘርናም ቀድሞ አለ!', 'error')
    else:
        new_staff = User(
            telegram_id=int(os.urandom(4).hex(), 16),
            username=username,
            phone=role.upper(),
            balance=0.0
        )
        db.session.add(new_staff)
        db.session.commit()
        flash(f'አዲስ {role} በተሳካ ሁኔታ ተጨመረ!', 'success')
    return redirect(url_for('admin.dashboard'))

# ዳታዎችን (ተጠቃሚ ወይም ትራንዛክሽን) መደለት
@admin_bp.route('/admin/delete/<string:data_type>/<int:item_id>', methods=['POST'])
@admin_required
def delete_data(data_type, item_id):
    if data_type == 'user':
        item = User.query.get_or_404(item_id)
        db.session.delete(item)
        flash('ተጠቃሚው ተሰርዟል።', 'success')
    elif data_type == 'transaction':
        item = Transaction.query.get_or_404(item_id)
        db.session.delete(item)
        flash('ትራንዛክሽኑ ተሰርዟል።', 'success')
    db.session.commit()
    return redirect(url_for('admin.dashboard'))

# የዊዝድሮዋል ጥያቄ ማጽደቅ
@admin_bp.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def approve_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('የገንዘብ ማውጣት ጥያቄው ጸድቋል!', 'success')
    else:
        flash('ትራንዛክሽኑ አልተገኘም ወይም ቀድሞ ተሰርቷል።', 'error')
    return redirect(url_for('admin.dashboard'))

# የዊዝድሮዋል ጥያቄ ውድቅ ማድረግ እና መመለስ
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
        flash('የገንዘብ ማውጣት ጥያቄው ውድቅ ተደርጎ ወደ ዋናው ሂሳብ ተመልሷል።', 'success')
    else:
        flash('ትራንዛክሽኑ አልተገኘም ወይም ቀድሞ ተሰርቷል።', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))