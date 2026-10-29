from datetime import datetime
from database import db

class User(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    
    balance = db.Column(db.Float, default=0.0)
    bonus_balance = db.Column(db.Float, default=20.0)
    coin = db.Column(db.Integer, default=0)
    
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    referrer_id = db.Column(db.BigInteger, nullable=True)
    is_blocked = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)  # ለ Soft Delete የተጨመረ
    
    transactions = db.relationship('Transaction', backref='user', lazy=True, cascade='all, delete-orphan')
    transfers_sent = db.relationship('Transfer', foreign_keys='Transfer.sender_id', backref='sender', lazy=True)
    transfers_received = db.relationship('Transfer', foreign_keys='Transfer.receiver_id', backref='receiver', lazy=True)
    game_histories = db.relationship('GameHistory', foreign_keys='GameHistory.user_id', backref='history_user', lazy=True)

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_super = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default='admin')          # 'admin' ወይም 'agent'
    can_edit_balance = db.Column(db.Boolean, default=True)   # ለአጀንት የሚሰጥ ፈቃድ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# አዲስ የተጨመረው የክፍያ ጌትዌዮች (Payment Gateways) ሞዴል
class PaymentGateway(db.Model):
    __tablename__ = 'payment_gateways'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)           # Telebirr, CBE Birr, etc.
    account_name = db.Column(db.String(100), nullable=True)    # የ አካውንት ባለቤት ስም
    account_number = db.Column(db.String(50), nullable=False)  # ስልክ ቁጥር ወይም የባንክ አካውንት
    purpose = db.Column(db.String(20), default='deposit')      # 'deposit' ወይም 'withdraw'
    logo_url = db.Column(db.String(255), nullable=True)        # የሎጎ ሊንክ/ፋይል ፓስ
    is_active = db.Column(db.Boolean, default=True)            # አክቲቭ መሆኑን ማሳያ (ON/OFF)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_code = db.Column(db.String(16), unique=True, nullable=True)
    hash_key = db.Column(db.String(64), unique=True, nullable=True)  
    status = db.Column(db.String(20), default='waiting')
    entry_price = db.Column(db.Float, nullable=False)
    pool = db.Column(db.Float, default=0.0)
    jackpot_pool = db.Column(db.Float, default=0.0)
    called_numbers = db.Column(db.String, default='')
    winner_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    participants = db.relationship('GameParticipant', backref='game', lazy=True, cascade='all, delete-orphan')
    winner = db.relationship('User', foreign_keys=[winner_id], backref='won_games', lazy=True)

class GameParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    cartela_number = db.Column(db.Integer, nullable=False)
    marked_numbers = db.Column(db.String, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('game_id', 'cartela_number', name='unique_cartela_per_game'),
    )

class GameHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, nullable=False)
    game_unique_code = db.Column(db.String(16))
    user_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=True)
    winner_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=True)
    winner_name = db.Column(db.String(64))
    winning_cartela = db.Column(db.Integer)
    winning_board_data = db.Column(db.Text)
    total_calls = db.Column(db.Integer)
    called_numbers_str = db.Column(db.Text)
    prize_amount = db.Column(db.Float)
    is_win = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # ለ 3 ወር ርዕስ ማጣሪያ የሚያገለግል
    finished_at = db.Column(db.DateTime, default=datetime.utcnow)

    winner_user = db.relationship('User', foreign_keys=[winner_id], backref='won_histories', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20)) # deposit, withdrawal
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(32))
    status = db.Column(db.String(20), default='pending') # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    deposit_phone = db.Column(db.String(20))
    transaction_id = db.Column(db.String(100), unique=True, index=True)
    sms_text = db.Column(db.Text)

    withdrawal_phone = db.Column(db.String(20))
    withdrawal_status = db.Column(db.String(20))
    admin_note = db.Column(db.Text)

class Transfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)