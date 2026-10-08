import os
import logging
import asyncio
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    CallbackQuery
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from flask import Flask
from database import db, init_db
from models import User, Transaction
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

WEBAPP_URL = f"https://{os.getenv('REPLIT_SLUG')}.replit.app" if os.getenv('REPLIT_SLUG') else "http://0.0.0.0:5000"
router = Router()

# Initialize Flask app for database context
app = Flask(__name__)
init_db(app)

# Game prices
GAME_PRICES = [10, 20, 50, 100]

@router.callback_query(lambda c: c.data.startswith('price_'))
async def process_price_selection(callback_query: CallbackQuery):
    """Handle price selection and create game"""
    try:
        # Extract price from callback data
        price = int(callback_query.data.split('_')[1])

        with app.app_context():
            user = User.query.filter_by(telegram_id=callback_query.from_user.id).first()
            if not user or user.balance < price:
                await callback_query.answer("Insufficient balance. Please deposit first.", show_alert=True)
                return

            # Create game through API
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{WEBAPP_URL}/game/create", json={'entry_price': price, 'user_id': user.id}) as response:
                    if response.status == 200:
                        data = await response.json()
                        game_id = data['game_id']

                        # Create WebApp button for cartela selection
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text="Select Your Cartela",
                                web_app=WebAppInfo(url=f"{WEBAPP_URL}/game/{game_id}/select_cartela")
                            )
                        ]])

                        await callback_query.message.edit_text(
                            f"Game created! Entry price: {price} Birr\n"
                            f"Please select your cartela number:",
                            reply_markup=keyboard
                        )
                    else:
                        await callback_query.answer("Failed to create game. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error processing price selection: {e}")
        await callback_query.answer("Sorry, there was an error. Please try again.", show_alert=True)

# States
class UserState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_deposit_amount = State()
    waiting_for_deposit_sms = State()
    waiting_for_withdrawal = State()

async def setup_bot():
    """Setup bot and dispatcher"""
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    bot = Bot(token=TOKEN)

    # Include router
    dp.include_router(router)

    logger.info("Bot setup completed")
    return bot, dp

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command and registration"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username

        # Check for referral
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        referrer_id = int(args[0]) if args else None

        with app.app_context():
            # Check if user exists
            user = User.query.filter_by(telegram_id=user_id).first()

            if not user:
                # New user registration
                user = User(
                    telegram_id=user_id,
                    username=username,
                    referrer_id=referrer_id
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"New user registered: {user_id} ({username})")

                keyboard = ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="📱 Share Phone Number", request_contact=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )

                await message.answer(
                    "Welcome to Addis Bingo! 🎮\n\n"
                    "Please share your phone number to complete registration.",
                    reply_markup=keyboard
                )
            else:
                # Returning user - show main menu
                await show_main_menu(message)

    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

async def show_main_menu(message: Message):
    """Show main menu with balance and options"""
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if not user:
                logger.error(f"User not found for main menu: {message.from_user.id}")
                await message.answer("Please register first using /start")
                return

            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🎮 Play Bingo")],
                    [KeyboardButton(text="💰 Deposit"), KeyboardButton(text="💳 Withdraw")],
                    [KeyboardButton(text="📊 My Stats")]
                ],
                resize_keyboard=True
            )

            await message.answer(
                f"🎯 Main Menu\n\n"
                f"💰 Balance: {user.balance:.2f} birr\n"
                f"🎮 Games played: {user.games_played}\n"
                f"🏆 Games won: {user.games_won}\n",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error showing main menu: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(F.contact)
async def process_phone_number(message: Message):
    """Handle shared contact information"""
    if not message.contact or message.contact.user_id != message.from_user.id:
        await message.answer("Please share your own contact information.")
        return

    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if not user:
                await message.answer("Please use /start first!")
                return

            user.phone = message.contact.phone_number
            db.session.commit()
            logger.info(f"Phone number registered for user: {message.from_user.id}")

            bot = Bot(token=TOKEN)
            bot_info = await bot.get_me()
            referral_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"

            await message.answer(
                "✅ Registration complete!\n\n"
                f"Your referral link: {referral_link}\n\n"
                "Share this link with friends and earn 20 birr when they:\n"
                "1. Register and verify their phone number\n"
                "2. Make their first deposit\n"
                "3. Play their first game\n",
                reply_markup=ReplyKeyboardRemove()
            )

            # Show main menu
            await show_main_menu(message)
    except Exception as e:
        logger.error(f"Error processing phone number: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")


@router.message(F.text == "🎮 Play Bingo")
async def process_play_command(message: Message):
    """Handle play command - show game price options"""
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()

            if not user:
                await message.answer("Please register first using /start")
                return

            # Create buttons for each price option
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{price} Birr",
                    callback_data=f"price_{price}"
                )] for price in GAME_PRICES
            ])

            await message.answer(
                "Choose your game entry price:",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error processing play command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(F.text == "💰 Deposit")
async def process_deposit_command(message: Message, state: FSMContext):
    """Handle deposit command"""
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if not user:
                await message.answer("Please register first using /start")
                return

            await state.set_state(UserState.waiting_for_deposit_amount)
            await message.answer(
                "💰 Enter the amount you want to deposit (in birr):\n\n"
                "Minimum: 10 birr\n"
                "Maximum: 1000 birr\n"
            )
    except Exception as e:
        logger.error(f"Error processing deposit command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(UserState.waiting_for_deposit_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    """Handle deposit amount input"""
    try:
        amount = float(message.text)
        if amount < 10:
            await message.answer("⚠️ Minimum deposit amount is 10 birr")
            return
        if amount > 1000:
            await message.answer("⚠️ Maximum deposit amount is 1000 birr")
            return

        # Store amount in state
        await state.update_data(deposit_amount=amount)

        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()

            # Create pending transaction
            transaction = Transaction(
                user_id=user.id,
                type='deposit',
                amount=amount,
                status='pending'
            )
            db.session.add(transaction)
            db.session.commit()

            await state.set_state(UserState.waiting_for_deposit_sms)
            await message.answer(
                f"✅ Amount confirmed: {amount} birr\n\n"
                "Please complete your deposit:\n\n"
                "1. Send money to one of these accounts:\n"
                "   - CBE: 1000123456 (Abebe)\n"
                "   - Telebirr: 0911111111\n"
                "2. Wait for confirmation\n\n"
                "⚠️ Your deposit will be processed automatically once received."
            )
    except ValueError:
        await message.answer("⚠️ Please enter a valid amount")
    except Exception as e:
        logger.error(f"Error processing deposit amount: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

async def send_notification(user_id: int, message: str):
    """Send a notification to a user through Telegram Bot API securely."""
    try:
        logger.info(f"Attempting to send notification to user {user_id}")
        bot = Bot(token=TOKEN)  # Using environment variable

        # Send message with HTML formatting
        sent_message = await bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="HTML"  # Support HTML formatting
        )

        logger.info(f"Successfully sent notification to user {user_id}: {message}")
        return sent_message
    except Exception as e:
        logger.error(f"Failed to send notification to user {user_id}: {e}")
        raise

async def process_deposit_confirmation(data: dict):
    """Handle deposit confirmation from webhook"""
    try:
        # Extract data from webhook
        received_amount = float(data.get('amount', 0))
        received_phone = data.get('phone')

        logger.info(f"Processing deposit confirmation: amount={received_amount}, phone={received_phone}")

        with app.app_context():
            # Find user by phone number
            user = User.query.filter_by(phone=received_phone).first()
            if not user:
                error_msg = f"No user found with phone: {received_phone}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Get pending transaction
            transaction = Transaction.query.filter_by(
                user_id=user.id,
                type='deposit',
                status='pending',
                amount=received_amount
            ).order_by(Transaction.created_at.desc()).first()

            if transaction:
                # Auto-approve the deposit
                transaction.status = 'completed'
                transaction.completed_at = datetime.utcnow()

                # Update user balance
                user.balance += received_amount
                db.session.commit()

                # Send notification using secure method
                await send_notification(
                    user_id=user.telegram_id,
                    message=f"✅ <b>Deposit Approved!</b>\n\n"
                           f"Amount: {received_amount:.2f} birr\n"
                           f"New Balance: {user.balance:.2f} birr"
                )
                logger.info(f"Deposit approved for user {user.id}: {received_amount} birr")
            else:
                error_msg = f"No pending deposit found for user {user.id} with amount {received_amount}"
                logger.error(error_msg)
                raise ValueError(error_msg)

    except Exception as e:
        logger.error(f"Error processing deposit confirmation: {e}")
        raise

@router.message(F.text == "💳 Withdraw")
async def process_withdraw_command(message: Message, state: FSMContext):
    """Handle withdraw command"""
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if not user:
                await message.answer("Please register first using /start")
                return

            if user.balance < 100:
                await message.answer("⚠️ Minimum withdrawal amount is 100 birr")
                return

            await state.set_state(UserState.waiting_for_withdrawal)
            await message.answer(
                "💳 Withdrawal Rules:\n\n"
                "1. Minimum: 100 birr\n"
                "2. Must have played at least 5 games\n"
                "3. Processing time: 24 hours\n\n"
                "Reply with the amount you want to withdraw:"
            )
    except Exception as e:
        logger.error(f"Error processing withdraw command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(F.text == "📊 My Stats")
async def process_stats_command(message: Message):
    """Handle stats command"""
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if not user:
                await message.answer("Please register first using /start")
                return

            # Get transaction history
            transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).limit(5).all()

            stats = (
                f"📊 Your Stats\n\n"
                f"💰 Current Balance: {user.balance:.2f} birr\n"
                f"🎮 Games Played: {user.games_played}\n"
                f"🏆 Games Won: {user.games_won}\n\n"
                f"Recent Transactions:\n"
            )

            for tx in transactions:
                stats += f"{'➕' if tx.amount > 0 else '➖'} {abs(tx.amount)} birr - {tx.type} ({tx.status})\n"

            await message.answer(stats)
    except Exception as e:
        logger.error(f"Error processing stats command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(UserState.waiting_for_withdrawal)
async def process_withdrawal_request(message: Message, state: FSMContext):
    """Handle withdrawal amount input"""
    try:
        amount = float(message.text)
        if amount < 100:
            await message.answer("⚠️ Minimum withdrawal amount is 100 birr")
            return

        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if amount > user.balance:
                await message.answer("⚠️ Insufficient balance")
                return

            # Create withdrawal transaction
            transaction = Transaction(
                user_id=user.id,
                type='withdraw',
                amount=-amount,  # Negative amount for withdrawals
                status='pending',
                withdrawal_phone=user.phone
            )
            db.session.add(transaction)
            db.session.commit()

            await message.answer(
                "✅ Withdrawal request received!\n\n"
                f"Amount: {amount} birr\n"
                "Status: Pending admin approval\n\n"
                "You'll receive a notification once it's processed."
            )
    except ValueError:
        await message.answer("⚠️ Please enter a valid amount")
        return
    except Exception as e:
        logger.error(f"Error processing withdrawal request: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

    await state.clear()
    await show_main_menu(message)

async def main():
    """Main entry point for the bot"""
    try:
        logger.info("Starting bot...")
        bot, dp = await setup_bot()

        # Start polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")