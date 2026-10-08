import os

# Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]

# Game Configuration
CARTELA_SIZE = 100
MIN_PLAYERS = 2
GAME_PRICES = [10, 20, 50, 100]  # in birr
MIN_GAMES_FOR_WITHDRAWAL = 5
MIN_WINS_FOR_WITHDRAWAL = 1
REFERRAL_BONUS = 20  # in birr

# Admin Panel Configuration
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")

# Database Configuration
SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Flask Configuration
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000