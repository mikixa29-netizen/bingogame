import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

def init_db(app):
    database_url = os.environ.get("DATABASE_URL")
    
    # PostgreSQL URL ፎርማት ማስተካከያ (Render ላይ አስፈላጊ ከሆነ)
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
        
        # 'is_blocked' የሚባል カラム (Column) ከሌለ በራሱ ጨምሮ 500 Internal Server Error እንዳያመጣ መከላከል
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE \"user\" ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE;"))
                conn.commit()
        except Exception:
            # Column ቀደም ብሎ ካለ ወይም ዳታቤዙ አዲስ ከሆነ ችግር እንዳይፈጥር ማለፍ
            pass