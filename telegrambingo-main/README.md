# Bingo Game Bot

A Telegram-based Bingo game bot that enables multiplayer Bingo gameplay through an interactive mini-app interface.

## Features

- Supports multiplayer Bingo with flexible player count
- Real-time number calling with consistent board generation
- Dynamic board marking with free center space
- Responsive web-based game interface integrated with Telegram
- PostgreSQL database for robust game state management
- Webhook support for external automation systems
- Telegram bot backend providing seamless game coordination

## Tech Stack

- Python 3.11
- Flask (Web Framework)
- aiogram (Telegram Bot Framework)
- PostgreSQL (Database)
- SQLAlchemy (ORM)
- Bootstrap (Frontend)

## Dependencies

```
aiogram>=3.18.0
email-validator>=2.2.0
flask-login>=0.6.3
flask>=3.1.0
flask-sqlalchemy>=3.1.1
gunicorn>=23.0.0
psycopg2-binary>=2.9.10
python-dotenv>=1.0.1
sqlalchemy>=2.0.38
twilio>=9.4.6
flask-wtf>=1.2.2
aiohttp>=3.11.13
requests>=2.32.3
```

## Setup Instructions

1. Clone the repository
```bash
git clone https://github.com/addis012/telegrambingo.git
cd telegrambingo
```

2. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up environment variables in `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
DATABASE_URL=postgresql://user:password@host:port/dbname
SESSION_SECRET=your_secret_key
```

5. Initialize the database
```bash
flask db upgrade
```

6. Run the application
```bash
python main.py
```

## Project Structure

```
├── app.py              # Flask application
├── bot.py              # Telegram bot implementation
├── database.py         # Database configuration
├── game_logic.py       # Bingo game logic
├── models.py           # Database models
├── static/            # Static files (CSS, JS)
└── templates/         # HTML templates
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Webhook Configuration

For webhook setup instructions (e.g., for Tasker integration), see `tasker_webhook_instructions.txt`.