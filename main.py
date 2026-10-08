import os
import asyncio
from app import app
from bot import main as bot_main
from multiprocessing import Process
import signal
import sys

def signal_handler(sig, frame):
    print('Shutting down gracefully...')
    sys.exit(0)

def run_flask():
    # Use gunicorn configuration
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

    options = {
        'bind': '0.0.0.0:5000',
        'workers': 1,
        'reload': True
    }
    FlaskApplication(app, options).run()

def run_bot():
    asyncio.run(bot_main())

if __name__ == "__main__":
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start Flask in a separate process
    flask_process = Process(target=run_flask)
    flask_process.start()

    try:
        # Run the bot in the main process
        run_bot()
    except KeyboardInterrupt:
        print("Received keyboard interrupt, shutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Cleanup
        if flask_process.is_alive():
            flask_process.terminate()
            flask_process.join()
        sys.exit(0)