import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple

class BingoGame:
    def __init__(self, game_id: int, entry_price: int = 10):
        self.game_id = game_id
        self.entry_price = entry_price
        self.pool = 0
        self.players: Dict[int, dict] = {}  # user_id -> {board: List[int], marked: List[int]}
        self.called_numbers: List[int] = []
        self.status = "waiting"  # waiting, active, finished
        self.winner_id = None
        self.created_at = datetime.utcnow()
        self.finished_at = None
        self.min_players = 1  # Temporarily set to 1 for testing
        self.max_players = 100  # Maximum players allowed
        self.last_call_time = None

    def generate_board(self, cartela_number: int) -> List[int]:
        """Generate a 5x5 BINGO board with consistent numbers based on cartela number."""
        # Use cartela number as seed for random number generation
        random.seed(cartela_number)

        # Generate numbers for each column with proper ranges
        b_numbers = random.sample(range(1, 16), 5)
        i_numbers = random.sample(range(16, 31), 5)
        n_numbers = random.sample(range(31, 46), 5)
        g_numbers = random.sample(range(46, 61), 5)
        o_numbers = random.sample(range(61, 76), 5)

        # Reset random seed
        random.seed()

        board = []
        for i in range(5):
            board.extend([b_numbers[i], i_numbers[i], n_numbers[i], g_numbers[i], o_numbers[i]])

        # Make center square (index 12) a free space by marking it automatically
        return board

    def add_player(self, user_id: int, cartela_number: int = None) -> List[int]:
        """Add a player and generate their board."""
        if user_id in self.players or len(self.players) >= self.max_players:
            return []

        if cartela_number is None:
            # Generate a random unused cartela number
            used_cartelas = set(p.get('cartela_number', 0) for p in self.players.values())
            available = [n for n in range(1, 101) if n not in used_cartelas]
            cartela_number = random.choice(available) if available else 0

        board = self.generate_board(cartela_number)
        self.players[user_id] = {
            'board': board,
            'marked': [board[12]],  # Center square is automatically marked
            'cartela_number': cartela_number
        }
        self.pool += self.entry_price

        # Auto-start if we reach minimum players
        if len(self.players) >= self.min_players:
            self.start_game()

        return board

    def call_number(self) -> Optional[str]:
        """Call the next random number if the game is active."""
        if self.status != "active":
            return None

        # Get list of uncalled numbers
        available = [n for n in range(1, 76) if n not in self.called_numbers]
        if not available:
            self.status = "finished"  # End game if all numbers are called
            return None

        # Call a new number
        number = random.choice(available)
        self.called_numbers.append(number)
        self.last_call_time = datetime.utcnow()
        return self.format_number(number)

    @staticmethod
    def format_number(number: int) -> str:
        """Format a number into BINGO format (e.g., B-12)."""
        if 1 <= number <= 15:
            prefix = "B"
        elif 16 <= number <= 30:
            prefix = "I"
        elif 31 <= number <= 45:
            prefix = "N"
        elif 46 <= number <= 60:
            prefix = "G"
        else:
            prefix = "O"
        return f"{prefix}-{number}"

    def mark_number(self, user_id: int, number: int) -> bool:
        """Mark a number on a player's board."""
        if user_id not in self.players:
            return False

        player = self.players[user_id]
        # Only allow marking numbers that are both on the player's board and have been called
        if number in player['board'] and number in self.called_numbers:
            if number not in player['marked']:
                player['marked'].append(number)
                player['marked'].sort()  # Keep marked numbers sorted
            return True
        return False

    def check_winner(self, user_id: int) -> Tuple[bool, str]:
        """Check if a player has won."""
        if user_id not in self.players:
            return False, "Player not in game"

        player = self.players[user_id]
        marked = set(player['marked'])
        board = player['board']

        # Validate that all marked numbers are actually on the board and have been called
        for num in marked:
            if num not in board and num != board[12]:  # Allow center free space
                return False, "Invalid marked numbers detected"
            if num not in self.called_numbers and num != board[12]:  # Allow center free space
                return False, "Number has not been called yet"

        # Check rows
        for i in range(0, 25, 5):
            if all(board[i + j] in marked for j in range(5)):
                return True, "Winner - Row complete!"

        # Check columns
        for i in range(5):
            if all(board[i + j*5] in marked for j in range(5)):
                return True, "Winner - Column complete!"

        # Check diagonals
        if all(board[i] in marked for i in [0, 6, 12, 18, 24]):
            return True, "Winner - Diagonal complete!"
        if all(board[i] in marked for i in [4, 8, 12, 16, 20]):
            return True, "Winner - Diagonal complete!"

        return False, "Keep playing"

    def start_game(self) -> bool:
        """Start the game if enough players have joined."""
        if len(self.players) < self.min_players:
            return False
        self.status = "active"
        # Call first number automatically when game starts
        self.call_number() 
        return True

    def end_game(self, winner_id: int):
        """End the game and set the winner."""
        self.winner_id = winner_id
        self.status = "finished"
        self.finished_at = datetime.utcnow()