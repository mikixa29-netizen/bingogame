from datetime import datetime
from database import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    
    # 3-Tier Balance Architecture
    balance = db.Column(db.Float, default=0.0)          # Main Balance (deposits & wins, withdrawable)[cite: 5]
    bonus_balance = db.Column(db.Float, default=20.0)   # Bonus Balance (20 Birr sign-up bonus, play-only)[cite: 5]
    coin = db.Column(db.Integer, default=0)             # Coin balance (10 coins = 10 Birr Bonus)[cite: 5]
    
    games_played = db.Column(db.Integer, default=0)[cite: 5]
    games_won = db.Column(db.Integer, default=0)[cite: 5]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)[cite: 5]
    referrer_id = db.Column(db.BigInteger, nullable=True)[cite: 5]
    
    # ዩዘርን ማገድ (Block) ወይም መክፈት (Unblock) ለማድረግ የተጨመረ መስክ[cite: 5]
    is_blocked = db.Column(db.Boolean, default=False)[cite: 5]

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default='waiting')  # waiting, active, finished[cite: 5]
    entry_price = db.Column(db.Float, nullable=False)[cite: 5]
    pool = db.Column(db.Float, default=0.0)[cite: 5]
    called_numbers = db.Column(db.String, default='')  # Store as comma-separated numbers[cite: 5]
    winner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)[cite: 5]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)[cite: 5]
    finished_at = db.Column(db.DateTime)[cite: 5]

    # Relationships[cite: 5]
    participants = db.relationship('GameParticipant', backref='game', lazy=True)[cite: 5]
    winner = db.relationship('User', backref='won_games', lazy=True)[cite: 5]

class GameParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)[cite: 5]
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)[cite: 5]
    cartela_number = db.Column(db.Integer, nullable=False)[cite: 5]
    marked_numbers = db.Column(db.String, default='')  # Store as comma-separated numbers[cite: 5]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)[cite: 5]

    __table_args__ = (
        db.UniqueConstraint('game_id', 'cartela_number', name='unique_cartela_per_game'),
    )

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)[cite: 5]
    type = db.Column(db.String(20))  # deposit, withdraw, win, game_entry[cite: 5]
    amount = db.Column(db.Float, nullable=False)[cite: 5]
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed[cite: 5]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)[cite: 5]
    completed_at = db.Column(db.DateTime)[cite: 5]

    # For deposits[cite: 5]
    deposit_phone = db.Column(db.String(20))[cite: 5]
    transaction_id = db.Column(db.String(100))[cite: 5]
    sms_text = db.Column(db.Text)[cite: 5]

    # For withdrawals[cite: 5]
    withdrawal_phone = db.Column(db.String(20))[cite: 5]
    withdrawal_status = db.Column(db.String(20))  # pending, approved, rejected[cite: 5]
    admin_note = db.Column(db.Text)[cite: 5]