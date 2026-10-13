import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple

class BingoGame:
    def __init__(self, game_id: int, entry_price: int = 10, max_cards_per_player: int = 4):
        self.game_id = game_id
        self.entry_price = entry_price
        self.pool = 0.0
        self.players: Dict[int, List[dict]] = {} # user_id -> list of cards
        self.called_numbers: List[int] = []
        self.status = "waiting"  # waiting, countdown, active, finished
        self.winners: List[Dict[str, any]] = []
        self.created_at = datetime.utcnow()
        self.finished_at = None
        self.min_players = 2  
        self.max_cards_per_player = max_cards_per_player
        self.max_total_cards = 200
        self.last_call_time = None
        self.bonus_text = "Off"
        self.countdown_seconds = 30
        self.countdown_start_time = None

    def get_total_cards(self) -> int:
        return sum(len(cards) for cards in self.players.values())

    def update_pool_and_bonus(self):
        total_collected = self.get_total_cards() * self.entry_price
        
        if self.entry_price == 10:
            commission = 0.15
        elif self.entry_price == 20:
            commission = 0.20
        elif self.entry_price == 50:
            commission = 0.25
        elif self.entry_price == 100:
            commission = 0.30
        else:
            commission = 0.15
            
        self.pool = total_collected * (1 - commission)
        
        if self.pool >= 1500:
            self.bonus_text = "7%"
        elif self.pool >= 1000:
            self.bonus_text = "5%"
        elif self.pool >= 500:
            self.bonus_text = "4%"
        elif self.pool >= 200:
            self.bonus_text = "2%"
        else:
            self.bonus_text = "Off"
            
        return self.pool, self.bonus_text

    def generate_board(self, cartela_number: int) -> List[int]:
        random.seed(cartela_number)
        b_numbers = random.sample(range(1, 16), 5)
        i_numbers = random.sample(range(16, 31), 5)
        n_numbers = random.sample(range(31, 46), 5)
        g_numbers = random.sample(range(46, 61), 5)
        o_numbers = random.sample(range(61, 76), 5)
        random.seed()

        board = []
        for i in range(5):
            board.extend([b_numbers[i], i_numbers[i], n_numbers[i], g_numbers[i], o_numbers[i]])
        return board

    def add_player_card(self, user_id: int, username: str = "Player", cartela_number: int = None) -> Tuple[bool, str, Optional[List[int]]]:
        if self.status not in ["waiting", "countdown"]:
            return False, "Game already started or finished", None

        if user_id not in self.players:
            self.players[user_id] = []

        if len(self.players[user_id]) >= self.max_cards_per_player:
            return False, f"Maximum {self.max_cards_per_player} cards allowed per player", None

        if self.get_total_cards() >= self.max_total_cards:
            return False, "Game is full (maximum 200 cards reached)", None

        used_cartelas = set(
            card['cartela_number'] 
            for cards in self.players.values() 
            for card in cards
        )

        if cartela_number is None:
            available = [n for n in range(1, 201) if n not in used_cartelas]
            cartela_number = random.choice(available) if available else random.randint(201, 999)
        elif cartela_number in used_cartelas:
            return False, "Cartela number already taken in this game", None

        board = self.generate_board(cartela_number)
        card_data = {
            'board': board,
            'marked': [board[12]],
            'cartela_number': cartela_number,
            'username': username
        }
        self.players[user_id].append(card_data)
        
        self.update_pool_and_bonus()

        if len(self.players) >= self.min_players and self.status == "waiting":
            self.status = "countdown"
            self.countdown_start_time = datetime.utcnow()

        return True, "Card added successfully", board

    def get_remaining_countdown(self) -> int:
        if self.status == "countdown" and self.countdown_start_time:
            elapsed = (datetime.utcnow() - self.countdown_start_time).total_seconds()
            remaining = self.countdown_seconds - elapsed
            if remaining <= 0:
                self.start_game()
                return 0
            return int(remaining)
        return self.countdown_seconds

    def update_active_game(self):
        if self.status == "active":
            if not self.last_call_time:
                self.call_number()
            else:
                elapsed = (datetime.utcnow() - self.last_call_time).total_seconds()
                if elapsed >= 3:
                    self.call_number()

    def player_leave(self, user_id: int) -> Tuple[bool, str, bool]:
        if user_id not in self.players:
            return False, "Player not found in this game", False

        balance_deducted = False
        if self.status in ["countdown", "active"]:
            balance_deducted = True

        del self.players[user_id]
        self.update_pool_and_bonus()

        if self.status == "active" and len(self.players) < self.min_players:
            self.status = "finished"
            self.finished_at = datetime.utcnow()

        return True, "Player left successfully", balance_deducted

    def call_number(self) -> Optional[str]:
        if self.status != "active":
            return None
        available = [n for n in range(1, 76) if n not in self.called_numbers]
        if not available:
            self.status = "finished"
            return None
        number = random.choice(available)
        self.called_numbers.append(number)
        self.last_call_time = datetime.utcnow()

        # Automatic marking & checking win condition for all cards automatically
        for u_id, cards in self.players.items():
            for c_idx, card in enumerate(cards):
                if number in card['board'] and number not in card['marked']:
                    card['marked'].append(number)
                    card['marked'].sort()
                
                # Check if this card has won automatically
                if self.check_winner_silent(u_id, c_idx):
                    winner_entry = {
                        'user_id': u_id,
                        'card_index': c_idx,
                        'username': card.get('username', 'Player'),
                        'cartela_number': card['cartela_number'],
                        'board': card['board'],
                        'marked': card['marked']
                    }
                    if not any(w['user_id'] == u_id and w['card_index'] == c_idx for w in self.winners):
                        self.winners.append(winner_entry)

        if self.winners:
            self.status = "finished"
            self.finished_at = datetime.utcnow()

        return self.format_number(number)

    @staticmethod
    def format_number(number: int) -> str:
        if 1 <= number <= 15: prefix = "B"
        elif 16 <= number <= 30: prefix = "I"
        elif 31 <= number <= 45: prefix = "N"
        elif 46 <= number <= 60: prefix = "G"
        else: prefix = "O"
        return f"{prefix}-{number}"

    def mark_number(self, user_id: int, card_index: int, number: int) -> bool:
        if user_id not in self.players or card_index >= len(self.players[user_id]):
            return False
        card = self.players[user_id][card_index]
        if number in card['board'] and number in self.called_numbers:
            if number not in card['marked']:
                card['marked'].append(number)
                card['marked'].sort()
            return True
        return False

    def check_winner_silent(self, user_id: int, card_index: int) -> bool:
        if user_id not in self.players or card_index >= len(self.players[user_id]):
            return False

        card = self.players[user_id][card_index]
        marked = set(card['marked'])
        board = card['board']

        for num in marked:
            if num not in board and num != board[12]:
                return False
            if num not in self.called_numbers and num != board[12]:
                return False

        for i in range(0, 25, 5):
            if all(board[i + j] in marked for j in range(5)):
                return True

        for i in range(5):
            if all(board[i + j*5] in marked for j in range(5)):
                return True

        if all(board[i] in marked for i in [0, 6, 12, 18, 24]):
            return True
        if all(board[i] in marked for i in [4, 8, 12, 16, 20]):
            return True

        if all(board[i] in marked for i in [0, 4, 20, 24]):
            return True

        return False

    def check_winner(self, user_id: int, card_index: int) -> Tuple[bool, str]:
        is_w = self.check_winner_silent(user_id, card_index)
        if is_w:
            return True, "Winner - Complete!"
        return False, "Keep playing"

    def claim_bingo(self, user_id: int, card_index: int) -> Tuple[bool, str, float]:
        if self.status != "active" and self.status != "finished":
            return False, "Game is not active", 0.0

        is_win, msg = self.check_winner(user_id, card_index)
        if not is_win and not self.winners:
            return False, msg, 0.0

        card = self.players[user_id][card_index]
        winner_entry = {
            'user_id': user_id,
            'card_index': card_index,
            'username': card.get('username', 'Player'),
            'cartela_number': card['cartela_number'],
            'board': card['board'],
            'marked': card['marked']
        }
        
        if not any(w['user_id'] == user_id and w['card_index'] == card_index for w in self.winners):
            self.winners.append(winner_entry)

        self.status = "finished"
        self.finished_at = datetime.utcnow()
        prize_per_winner = self.pool / len(self.winners) if self.winners else 0.0
        return True, "Bingo verified successfully!", prize_per_winner

    def start_game(self) -> bool:
        if len(self.players) < self.min_players:
            return False
        self.status = "active"
        self.call_number() 
        return True

    def end_game(self):
        self.status = "finished"
        self.finished_at = datetime.utcnow()