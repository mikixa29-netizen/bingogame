import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

def init_db(app):
    database_url = os.environ.get("DATABASE_URL")
    
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    db.init_app(app)

    with app.app_context():
        import models  
        db.create_all()
        
        with db.engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            
            # 1. መጀመሪያ የ Foreign Key አምዶችን ወደ BIGINT መቀየር (የጥገኝነት ስህተት እንዳይፈጠር)
            foreign_key_alterations = [
                'ALTER TABLE "game_participant" ALTER COLUMN user_id TYPE BIGINT;',
                'ALTER TABLE "transaction" ALTER COLUMN user_id TYPE BIGINT;',
                'ALTER TABLE "transfer" ALTER COLUMN sender_id TYPE BIGINT;',
                'ALTER TABLE "transfer" ALTER COLUMN receiver_id TYPE BIGINT;',
                'ALTER TABLE "game" ALTER COLUMN winner_id TYPE BIGINT;',
                'ALTER TABLE "game_history" ALTER COLUMN user_id TYPE BIGINT;',
                'ALTER TABLE "game_history" ALTER COLUMN winner_id TYPE BIGINT;'
            ]
            
            for sql in foreign_key_alterations:
                try:
                    connection.execute(text(sql))
                except Exception:
                    pass

            # 2. በመቀጠል የ user ሰንጠረዥ ዋና ቁልፎችን እና ቴሌግራም ID ወደ BIGINT መቀየር
            primary_key_alterations = [
                'ALTER TABLE "user" ALTER COLUMN telegram_id TYPE BIGINT;',
                'ALTER TABLE "user" ALTER COLUMN id TYPE BIGINT;'
            ]
            
            for sql in primary_key_alterations:
                try:
                    connection.execute(text(sql))
                except Exception:
                    pass

            # 3. ሌሎች አዲስ አምዶች (Columns) ካሉ መፈተሽና መጨመር
            user_columns_to_add = [
                ('is_blocked', 'BOOLEAN DEFAULT FALSE'),
                ('bonus_balance', 'DOUBLE PRECISION DEFAULT 20.0'),
                ('coin', 'INTEGER DEFAULT 0'),
                ('games_played', 'INTEGER DEFAULT 0'),
                ('games_won', 'INTEGER DEFAULT 0'),
                ('referrer_id', 'BIGINT'),
                ('phone', 'VARCHAR(30)')
            ]
            for col_name, col_type in user_columns_to_add:
                try:
                    connection.execute(text(f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type};'))
                except Exception:
                    pass

            game_columns_to_add = [
                ('hash_key', 'VARCHAR(64)'),
                ('jackpot_pool', 'DOUBLE PRECISION DEFAULT 0.0'),
                ('unique_code', 'VARCHAR(16)')
            ]
            for col_name, col_type in game_columns_to_add:
                try:
                    connection.execute(text(f'ALTER TABLE "game" ADD COLUMN {col_name} {col_type};'))
                except Exception:
                    pass

            history_columns_to_add = [
                ('game_unique_code', 'VARCHAR(16)'),
                ('winning_board_data', 'TEXT'),
                ('is_win', 'BOOLEAN DEFAULT FALSE'),
                ('user_id', 'BIGINT')
            ]
            for col_name, col_type in history_columns_to_add:
                try:
                    connection.execute(text(f'ALTER TABLE "game_history" ADD COLUMN {col_name} {col_type};'))
                except Exception:
                    pass

            transaction_columns_to_add = [
                ('payment_method', 'VARCHAR(32)'),
                ('transaction_id', 'VARCHAR(100)'),
                ('deposit_phone', 'VARCHAR(20)'),
                ('sms_text', 'TEXT'),
                ('withdrawal_phone', 'VARCHAR(20)'),
                ('withdrawal_status', 'VARCHAR(20)'),
                ('admin_note', 'TEXT')
            ]
            for col_name, col_type in transaction_columns_to_add:
                try:
                    connection.execute(text(f'ALTER TABLE "transaction" ADD COLUMN {col_name} {col_type};'))
                except Exception:
                    pass