import os
import asyncio
from app import app
from bot import run_bot as bot_main  # እዚህ ጋር from bot import run_bot ተብሎ ተስተካክሏል
from multiprocessing import Process
import signal
import sys

def signal_handler(sig, frame):
    print('Shutting down gracefully...')
    sys.exit(0)

def run_flask():
    from gunicorn.app.base import BaseApplication

    class FlaskApplication(BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    # Render የሚሰጠውን ፖርት ይቀበላል፣ ካላገኘ 5000 ይጠቀማል
    port = int(os.environ.get('PORT', 5000))
    
    options = {
        'bind': f'0.0.0.0:{port}',
        'workers': 1,
        'reload': False  # Render ላይ error እንዳያመጣ False መሆን አለበት
    }
    FlaskApplication(app, options).run()

def run_bot():
    asyncio.run(bot_main())

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    flask_process = Process(target=run_flask)
    flask_process.start()

    try:
        run_bot()
    except KeyboardInterrupt:
        print("Received keyboard interrupt, shutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if flask_process.is_alive():
            flask_process.terminate()
            flask_process.join()
        sys.exit(0)