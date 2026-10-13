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
        import models  # Import models here to avoid circular imports
        db.create_all()
        
        # PostgreSQL አውቶማቲክ አምዶችን ለመጨመር ደህንነቱ የተጠበቀ መንገድ
        with db.engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            
            columns_to_add = [
                ('is_blocked', 'BOOLEAN DEFAULT FALSE'),
                ('bonus_balance', 'DOUBLE PRECISION DEFAULT 20.0'),
                ('coin', 'INTEGER DEFAULT 0'),
                ('games_played', 'INTEGER DEFAULT 0'),
                ('games_won', 'INTEGER DEFAULT 0'),
                ('referrer_id', 'BIGINT')
            ]
            
            for col_name, col_type in columns_to_add:
                try:
                    connection.execute(text(f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type};'))
                except Exception:
                    pass  # አምዱ ቀድሞውኑ ካለ ችግር ሳይፈጥር እንዲያልፍ