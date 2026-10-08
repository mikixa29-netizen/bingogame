from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from config import (
    ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY,
    FLASK_HOST, FLASK_PORT
)
from game_logic import BingoGame, Player

app = Flask(__name__)
app.secret_key = SECRET_KEY

# In-memory storage
games = []
players = {}

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
            
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
@admin_required
def dashboard():
    return render_template(
        'admin/dashboard.html',
        players=players,
        games=games,
        active_games=len([g for g in games if g.status == "active"]),
        total_players=len(players)
    )

@app.route('/admin/game/start', methods=['POST'])
@admin_required
def start_game():
    game_id = request.form.get('game_id')
    if game_id and games[int(game_id)].start_game():
        flash('Game started successfully')
    else:
        flash('Could not start game')
    return redirect(url_for('dashboard'))

@app.route('/admin/withdrawal/approve', methods=['POST'])
@admin_required
def approve_withdrawal():
    user_id = request.form.get('user_id')
    amount = float(request.form.get('amount'))
    
    if user_id in players:
        player = players[user_id]
        if player.balance >= amount:
            player.balance -= amount
            flash('Withdrawal approved')
        else:
            flash('Insufficient balance')
    else:
        flash('Player not found')
        
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
