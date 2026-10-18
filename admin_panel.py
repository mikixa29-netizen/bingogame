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
        
        # ከአድሚን ሞዴል ወይም ከኮንፊግ ማረጋገጥ
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
            flash('የተሳሳተ መግቢያ ስም ወይም የይለፍ ቃል!', 'error')
            
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

# የተጠቃሚን ዝርዝር ገቢ እና ወጪ ማየት (View Details)
@admin_bp.route('/admin/user/<int:user_id>/details')
@admin_required
def user_details(user_id):
    user = User.query.get_or_404(user_id)
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id.desc()).all()
    return render_template('admin/user_details.html', user=user, transactions=transactions)

# የተጠቃሚ ባላንስ፣ ቦነስ እና ኮይን ማስተካከል (Update User Balance)
@admin_bp.route('/admin/user/<int:user_id>/update', methods=['POST'])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        user.balance = float(request.form.get('balance', user.balance))
        user.bonus_balance = float(request.form.get('bonus_balance', user.bonus_balance))
        user.coin = int(request.form.get('coin', user.coin))
        db.session.commit()
        flash('የተጠቃሚው መረጃ በተሳካ ሁኔታ ተዘምኗል!', 'success')
    except Exception as e:
        flash('መረጃውን ማዘመን አልተቻለም: ' + str(e), 'error')
    return redirect(url_for('admin.dashboard'))

# ተጠቃሚን ማገድ ወይም መክፈት (Block / Unblock)
@admin_bp.route('/admin/user/<int:user_id>/toggle_block', methods=['POST'])
@admin_required
def toggle_block(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blocked = not user.is_blocked
    db.session.commit()
    status_text = 'ታግዷል' if user.is_blocked else 'ተከፍቷል'
    flash(f'ተጠቃሚው አሁን {status_text}!', 'success')
    return redirect(url_for('admin.dashboard'))

# አድሚን ወይም አጀንት በሮል (Role) ማከል (Superadmin only)
@admin_bp.route('/admin/staff/add', methods=['POST'])
@admin_required
def add_staff():
    if not session.get('is_super_admin'):
        flash('ሱፐር አድሚን ብቻ ነው አድሚን መመዝገብ የሚችለው!', 'error')
        return redirect(url_for('admin.dashboard'))
        
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'agent') # admin ወይም agent
    
    existing = Admin.query.filter_by(username=username).first()
    if existing:
        flash('ይህ ዩዘርናም ቀድሞ አለ!', 'error')
    else:
        new_admin = Admin(
            username=username,
            password_hash=hashlib.sha256(password.encode()).hexdigest(),
            is_super=(role == 'admin')
        )
        db.session.add(new_admin)
        db.session.commit()
        flash(f'አዲስ {role} በተሳካ ሁኔታ ተጨመረ!', 'success')
    return redirect(url_for('admin.dashboard'))

# አድሚን መሰረዝ
@admin_bp.route('/admin/staff/delete/<int:admin_id>', methods=['POST'])
@admin_required
def delete_staff(admin_id):
    if not session.get('is_super_admin'):
        flash('ፈቃድ የለዎትም!', 'error')
        return redirect(url_for('admin.dashboard'))
        
    adm = Admin.query.get_or_404(admin_id)
    db.session.delete(adm)
    db.session.commit()
    flash('አድሚኑ ተሰርዟል።', 'success')
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

# የዊዝድሮዋል ጥያቄ ማጽደቅ (Completed) -> ተጠቃሚው ስታስ/ሂስቶሪ ሲገባ ማየት ይችላል
@admin_bp.route('/admin/withdrawal/<int:tx_id>/approve', methods=['POST'])
@admin_required
def approve_withdrawal(tx_id):
    tx = Transaction.query.get(tx_id)
    if tx and tx.status == 'pending':
        tx.status = 'completed'
        tx.completed_at = datetime.utcnow()
        db.session.commit()
        flash('የገንዘብ ማውጣት ጥያቄው ጸድቋል (Completed)!', 'success')
    else:
        flash('ትራንዛክሽኑ አልተገኘም ወይም ቀድሞ ተሰርቷል።', 'error')
    return redirect(url_for('admin.dashboard'))

# የዊዝድሮዋል ጥያቄ ውድቅ ማድረግ (Rejected) እና ገንዘቡን መመለስ
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
        flash('የገንዘብ ማውጣት ጥያቄው ውድቅ ተደርጎ (Rejected) ገንዘቡ ተመልሷል!', 'success')
    else:
        flash('ትራንዛክሽኑ አልተገኘም ወይም ቀድሞ ተሰርቷል።', 'error')
    return redirect(url_for('admin.dashboard'))

# ዜና ማሰራጨት (Broadcast News) - በቀጥታ ቦቱ ላይ በራስ-ሰር እንዲታይ
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
        flash('ዜናው ተለጥፎ ቦቱ ላይ በራስ-ሰር እንዲታይ ተደረገ!', 'success')
    else:
        flash('እባክዎ የዜና ይዘት ያስገቡ!', 'error')
    return redirect(url_for('admin.dashboard'))

# የእንኳን ደህና መጡ ፎቶ ከስልክ ወይም ፒሲ መርጦ አድ ማድረግ (Welcome Image Upload)
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
            flash('የእንኳን ደህና መጡ ፎቶ ከስልክ/ፒሲ ተጭኖ ቦቱ ላይ ተስተካክሏል!', 'success')
            return redirect(url_for('admin.dashboard'))
            
    # በሊንክ ማስገባት ከፈለጉ
    image_url = request.form.get('image_url')
    if image_url:
        config['welcome_image_url'] = image_url
        with open(config_file, 'w') as f:
            json.dump(config, f)
        flash('የእንኳን ደህና መጡ ፎቶ ዩአርኤል ተዘምኗል!', 'success')
    else:
        flash('እባክዎ ፎቶ ይምረጡ ወይም ሊንክ ያስገቡ!', 'error')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    session.pop('is_super_admin', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin.login'))