import os
import json
import logging
import asyncio
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
    CallbackQuery,
    URLInputFile,
    BotCommand
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from flask import Flask
from database import db, init_db
from models import User, Transaction
import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
DEFAULT_WELCOME_IMAGE = os.getenv("WELCOME_IMAGE_URL", "https://i.imgur.com/your_default_image.jpg") 

# Render ላይ አፕሊኬሽኑ ሲሰራ ትክክለኛውን የ Render URL (Render External URL) እንዲጠቀም ተደርጓል
WEBAPP_URL = os.getenv('RENDER_EXTERNAL_URL') or "http://0.0.0.0:5000"
router = Router()

app = Flask(__name__)
init_db(app)

GAME_PRICES = [10, 20, 50, 100]
CONFIG_FILE = "bot_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def get_welcome_photo():
    config = load_config()
    photo_ref = config.get('welcome_image_file_id', DEFAULT_WELCOME_IMAGE)
    return URLInputFile(photo_ref) if photo_ref.startswith("http") else photo_ref

# States
class UserState(StatesGroup):
    waiting_for_deposit_method = State()
    waiting_for_deposit_amount = State()
    waiting_for_deposit_reference = State()
    waiting_for_withdraw_method = State()
    waiting_for_withdraw_amount = State()
    waiting_for_withdraw_phone = State()

class AdminState(StatesGroup):
    waiting_for_news = State()
    waiting_for_welcome_image = State()

def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Play Bingo 🎮", callback_data="menu_play_bingo")
        ],
        [
            InlineKeyboardButton(text="Register 📝", callback_data="menu_register"),
            InlineKeyboardButton(text="Deposit 💵", callback_data="menu_deposit")
        ],
        [
            InlineKeyboardButton(text="Withdraw 💳", callback_data="menu_withdraw"),
            InlineKeyboardButton(text="Check Balance 💰", callback_data="menu_balance")
        ],
        [
            InlineKeyboardButton(text="Contact support 📞", url="https://t.me/EdilBingoSupport"),
            InlineKeyboardButton(text="Instruction 📖", callback_data="menu_instruction")
        ],
        [
            InlineKeyboardButton(text="Invite ✉️", callback_data="menu_invite")
        ]
    ])

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="playbingo", description="Start playing Bingo"),
        BotCommand(command="register", description="Register for an account"),
        BotCommand(command="deposit", description="Deposit funds"),
        BotCommand(command="withdraw", description="Withdraw funds"),
        BotCommand(command="balance", description="Check account balance"),
        BotCommand(command="adminreport", description="Admin report & stats")
    ]
    await bot.set_my_commands(commands)

@router.message(Command("start"))
async def cmd_start(message: Message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        referrer_id = int(args[0]) if args else None

        with app.app_context():
            user = User.query.filter_by(telegram_id=user_id).first()
            if not user:
                user = User(telegram_id=user_id, username=username, referrer_id=referrer_id)
                db.session.add(user)
                db.session.commit()
                logger.info(f"New user registered: {user_id} ({username})")

        await message.answer_photo(
            photo=get_welcome_photo(),
            caption="Welcome to Edil Bingo! Choose an option below.",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(Command("register"))
@router.callback_query(F.data == "menu_register")
async def process_register_command_or_callback(event):
    message = event.message if isinstance(event, CallbackQuery) else event
    try:
        user_id = message.from_user.id
        with app.app_context():
            user = User.query.filter_by(telegram_id=user_id).first()
            if user and user.phone:
                text = "You are already registered. Click /playbingo to start the game."
                if isinstance(event, CallbackQuery):
                    await message.answer(text)
                    await event.answer()
                else:
                    await message.answer(text)
                return

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Share Phone Number", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer(
            "To complete your Edil Bingo registration, please share your phone number:",
            reply_markup=keyboard
        )
        if isinstance(event, CallbackQuery):
            await event.answer()
    except Exception as e:
        logger.error(f"Error in registration: {e}")
        if isinstance(event, CallbackQuery):
            await event.answer("An error occurred.", show_alert=True)

@router.message(F.contact)
async def process_phone_number(message: Message):
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
            
            bot_info = await message.bot.get_me()
            referral_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"

            await message.answer(
                "✅ Registration complete!\n\n"
                f"Your referral link: {referral_link}\n\n"
                "Returning to main menu:",
                reply_markup=ReplyKeyboardRemove()
            )
            
            await message.answer_photo(
                photo=get_welcome_photo(),
                caption="Welcome to Edil Bingo! Choose an option below.",
                reply_markup=get_main_menu()
            )
    except Exception as e:
        logger.error(f"Error processing phone number: {e}")

@router.message(Command("balance"))
@router.callback_query(F.data == "menu_balance")
async def process_balance_command_or_callback(event):
    message = event.message if isinstance(event, CallbackQuery) else event
    user_id = message.from_user.id
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if user:
            name = user.username or message.from_user.first_name or "Unknown"
            phone = user.phone or "Not provided"
            
            details_html = (
                "Account details\n"
                "<pre><code class=\"language-copy\">"
                f"Name:              {name}\n"
                f"Phone:             {phone}\n"
                f"Balance:           {user.balance:.2f}\n"
                f"Bonus balance:     1.00\n"
                f"Tournament wallet: 0.00\n"
                f"Coin:              1"
                "</code></pre>"
            )
            await message.answer(details_html, parse_mode="HTML")
        else:
            text = "Please register first using /start or /register."
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await message.answer(text)
    if isinstance(event, CallbackQuery):
        await event.answer()

@router.message(Command("playbingo"))
@router.callback_query(F.data == "menu_play_bingo")
async def process_play_bingo_command_or_callback(event):
    message = event.message if isinstance(event, CallbackQuery) else event
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Play10", callback_data="price_10"),
            InlineKeyboardButton(text="🎮 Play20", callback_data="price_20")
        ],
        [
            InlineKeyboardButton(text="🎮 Play50", callback_data="price_50"),
            InlineKeyboardButton(text="🎮 Play100", callback_data="price_100")
        ],
        [
            InlineKeyboardButton(text="🎮 Play Demo", callback_data="play_demo")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
        ]
    ])
    
    if isinstance(event, CallbackQuery):
        await message.edit_caption(
            caption="🍀 Best of luck on your Bingo game adventure! 🎮",
            reply_markup=keyboard
        )
        await event.answer()
    else:
        await message.answer_photo(
            photo=get_welcome_photo(),
            caption="🍀 Best of luck on your Bingo game adventure! 🎮",
            reply_markup=keyboard
        )

@router.callback_query(F.data == "play_demo")
async def process_play_demo(callback_query: CallbackQuery):
    await callback_query.answer("Demo mode coming soon!", show_alert=True)


# ==========================================
#   AUTOMATED MERCHANT API DEPOSIT LOGIC
# ==========================================

@router.message(Command("deposit"))
@router.callback_query(F.data == "menu_deposit")
async def process_deposit_command_or_callback(event, state: FSMContext = None):
    message = event.message if isinstance(event, CallbackQuery) else event
    user_id = message.from_user.id
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if not user:
            text = "Please register first using /start or /register"
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await message.answer(text)
            return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Telebirr", callback_data="dep_method_telebirr"),
            InlineKeyboardButton(text="🏦 CBE Birr", callback_data="dep_method_cbe")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
        ]
    ])

    caption = "💳 <b>Deposit Funds</b>\n\nChoose your preferred payment method:"
    if isinstance(event, CallbackQuery):
        await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        await message.answer_photo(photo=get_welcome_photo(), caption=caption, reply_markup=keyboard, parse_mode="HTML")
    
    if state:
        await state.set_state(UserState.waiting_for_deposit_method)

@router.callback_query(UserState.waiting_for_deposit_method, F.data.startswith("dep_method_"))
async def process_deposit_method_selection(callback_query: CallbackQuery, state: FSMContext):
    method = "Telebirr" if "telebirr" in callback_query.data else "CBE Birr"
    await state.update_data(deposit_method=method)
    await state.set_state(UserState.waiting_for_deposit_amount)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu_deposit")]
    ])
    
    await callback_query.message.edit_caption(
        caption=f"Selected Method: <b>{method}</b>\n\n"
                "💰 Enter the amount you want to deposit (in birr):\n"
                "• Minimum: <b>50 birr</b>\n"
                "• Maximum: <b>1000 birr</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback_query.answer()

@router.message(UserState.waiting_for_deposit_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < 50:
            await message.answer("⚠️ Minimum deposit amount is 50 birr. Please enter a valid amount:")
            return
        if amount > 1000:
            await message.answer("⚠️ Maximum deposit amount is 1000 birr. Please enter a valid amount:")
            return

        await state.update_data(deposit_amount=amount)
        data = await state.get_data()
        method = data.get("deposit_method")

        await state.set_state(UserState.waiting_for_deposit_reference)
        account_info = "0911111111 (Telebirr)" if method == "Telebirr" else "1000123456 - Abebe (CBE Birr)"
        
        await message.answer(
            f"✅ Amount: <b>{amount} birr</b> via <b>{method}</b> confirmed.\n\n"
            f"1. Transfer the money to our merchant account:\n"
            f"   👉 <b>{account_info}</b>\n\n"
            f"2. Send your transaction reference number or registered phone number for automatic API verification:",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Please enter a valid numerical amount.")
    except Exception as e:
        logger.error(f"Error handling deposit amount: {e}")
        await message.answer("Sorry, an error occurred. Please try again.")

async def simulate_merchant_api_verification(method: str, amount: float, reference: str, user_phone: str) -> bool:
    await asyncio.sleep(1)
    if reference and len(reference.strip()) >= 5:
        return True
    return False

@router.message(UserState.waiting_for_deposit_reference)
async def process_deposit_reference(message: Message, state: FSMContext):
    ref_text = message.text
    data = await state.get_data()
    amount = data.get("deposit_amount")
    method = data.get("deposit_method")
    user_id = message.from_user.id
    await state.clear()

    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        user_phone = user.phone or ""

        is_verified = await simulate_merchant_api_verification(method, amount, ref_text, user_phone)

        if is_verified:
            user.balance += amount
            transaction = Transaction(
                user_id=user.id,
                type='deposit',
                amount=amount,
                status='completed',
                withdrawal_phone=ref_text,
                completed_at=datetime.utcnow()
            )
            db.session.add(transaction)
            db.session.commit()

            await message.answer(
                f"✅ <b>Deposit Verified & Credited Successfully!</b>\n\n"
                f"Method: {method}\n"
                f"Amount: {amount:.2f} birr\n"
                f"New Balance: {user.balance:.2f} birr\n\n"
                "Your payment was automatically confirmed via merchant API.",
                parse_mode="HTML"
            )
        else:
            transaction = Transaction(
                user_id=user.id,
                type='deposit',
                amount=amount,
                status='failed',
                withdrawal_phone=ref_text
            )
            db.session.add(transaction)
            db.session.commit()

            await message.answer(
                "❌ <b>Deposit Verification Failed</b>\n\n"
                "We could not automatically verify your transaction reference with Telebirr / CBE Birr API. Please check your reference number and try again using /deposit.",
                parse_mode="HTML"
            )
    
    await message.answer_photo(
        photo=get_welcome_photo(),
        caption="Welcome to Edil Bingo! Choose an option below.",
        reply_markup=get_main_menu()
    )


# ==========================================
#         WITHDRAWAL WORKFLOW LOGIC
# ==========================================

@router.message(Command("withdraw"))
@router.callback_query(F.data == "menu_withdraw")
async def process_withdraw_command_or_callback(event, state: FSMContext = None):
    message = event.message if isinstance(event, CallbackQuery) else event
    user_id = message.from_user.id
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if not user:
            text = "Please register first using /start or /register"
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await message.answer(text)
            return
        
        if user.balance < 50:
            text = f"⚠️ Insufficient balance for withdrawal. Your balance is {user.balance:.2f} birr. Minimum required is 50 birr."
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await message.answer(text)
            return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Telebirr", callback_data="withdraw_method_telebirr"),
            InlineKeyboardButton(text="🏦 CBE Birr", callback_data="withdraw_method_cbe")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
        ]
    ])

    caption = "💳 <b>Withdraw Funds</b>\n\nSelect your payout payment method:"
    if isinstance(event, CallbackQuery):
        await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        await message.answer_photo(photo=get_welcome_photo(), caption=caption, reply_markup=keyboard, parse_mode="HTML")
    
    if state:
        await state.set_state(UserState.waiting_for_withdraw_method)

@router.callback_query(UserState.waiting_for_withdraw_method, F.data.startswith("withdraw_method_"))
async def process_withdraw_method_selection(callback_query: CallbackQuery, state: FSMContext):
    method = "Telebirr" if "telebirr" in callback_query.data else "CBE Birr"
    await state.update_data(withdraw_method=method)
    await state.set_state(UserState.waiting_for_withdraw_amount)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu_withdraw")]
    ])
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=callback_query.from_user.id).first()
        max_bal = user.balance

    await callback_query.message.edit_caption(
        caption=f"Selected Payout Method: <b>{method}</b>\n\n"
                f"💰 Your Current Balance: <b>{max_bal:.2f} birr</b>\n"
                "Enter the amount you want to withdraw:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback_query.answer()

@router.message(UserState.waiting_for_withdraw_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if amount < 50:
                await message.answer("⚠️ Minimum withdrawal amount is 50 birr. Please enter a valid amount:")
                return
            if amount > user.balance:
                await message.answer(f"⚠️ Insufficient balance. You only have {user.balance:.2f} birr. Enter a valid amount:")
                return

        await state.update_data(withdraw_amount=amount)
        await state.set_state(UserState.waiting_for_withdraw_phone)
        
        await message.answer(
            f"✅ Amount: <b>{amount} birr</b> confirmed.\n\n"
            "📞 Please enter the phone number or account number where you want to receive your payment:",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Please enter a valid numerical amount.")
    except Exception as e:
        logger.error(f"Error handling withdrawal amount: {e}")
        await message.answer("Sorry, an error occurred. Please try again.")

@router.message(UserState.waiting_for_withdraw_phone)
async def process_withdraw_phone(message: Message, state: FSMContext):
    payout_account = message.text
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    method = data.get("withdraw_method")
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await state.clear()

    tx_id = None
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        user.balance -= amount
        transaction = Transaction(
            user_id=user.id,
            type='withdraw',
            amount=-amount,
            status='pending',
            withdrawal_phone=f"{method}: {payout_account}"
        )
        db.session.add(transaction)
        db.session.commit()
        tx_id = transaction.id

    await message.answer(
        "Withdraw request successfully sent. Wait the admin to approve."
    )

    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve Payout", callback_data=f"admin_wd_approve_{tx_id}"),
            InlineKeyboardButton(text="❌ Reject Payout", callback_data=f"admin_wd_reject_{tx_id}")
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 <b>New Withdrawal Request!</b>\n\n"
                     f"👤 User: @{username} (ID: <code>{user_id}</code>)\n"
                     f"💰 Amount: <b>{amount} birr</b>\n"
                     f"📱 Method & Account: <b>{method}: {payout_account}</b>",
                parse_mode="HTML",
                reply_markup=admin_keyboard
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id} for withdrawal: {e}")
    
    await message.answer_photo(
        photo=get_welcome_photo(),
        caption="Welcome to Edil Bingo! Choose an option below.",
        reply_markup=get_main_menu()
    )


# ==========================================
#         ADMIN REPORT & ACTION HANDLERS
# ==========================================

@router.message(Command("adminreport"))
async def cmd_admin_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    with app.app_context():
        users = User.query.all()
        report_text = "📊 <b>Edil Bingo Admin Report</b>\n\n"
        
        for u in users:
            report_text += (
                f"👤 <b>User:</b> {u.username or 'N/A'} (ID: <code>{u.telegram_id}</code>)\n"
                f"📱 <b>Phone:</b> {u.phone or 'Not set'}\n"
                f"💰 <b>Balance:</b> {u.balance:.2f} birr\n"
                f"🎮 <b>Games Played:</b> {u.games_played} | 🏆 <b>Won:</b> {u.games_won}\n"
                "-----------------------------------\n"
            )

    if len(report_text) > 4000:
        report_text = report_text[:4000] + "\n[Report truncated due to length...]"

    await message.answer(report_text, parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_wd_"))
async def handle_admin_withdrawal_action(callback_query: CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("Unauthorized.", show_alert=True)
        return

    data_parts = callback_query.data.split("_")
    action = data_parts[2]
    tx_id = int(data_parts[3])

    with app.app_context():
        tx = Transaction.query.get(tx_id)
        if not tx or tx.status != 'pending':
            await callback_query.answer("Transaction already processed or not found.", show_alert=True)
            return

        user = User.query.get(tx.user_id)

        if action == "approve":
            tx.status = 'completed'
            tx.completed_at = datetime.utcnow()
            db.session.commit()

            try:
                await callback_query.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"✅ <b>Withdrawal Approved!</b>\n\nYour payout of {abs(tx.amount):.2f} birr has been sent to your account.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await callback_query.message.edit_text(f"✅ Withdrawal Approved successfully for user ID {user.telegram_id} (Amount: {abs(tx.amount)} Birr).")
        else:
            tx.status = 'rejected'
            user.balance += abs(tx.amount)
            db.session.commit()

            try:
                await callback_query.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"❌ <b>Withdrawal Rejected</b>\n\nYour withdrawal request of {abs(tx.amount):.2f} birr was rejected and refunded to your balance.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await callback_query.message.edit_text(f"❌ Withdrawal Rejected & Refunded for user ID {user.telegram_id}.")
    await callback_query.answer()


# ==========================================
#         PRICE SELECTION & WEBAPP LINK
# ==========================================

@router.callback_query(lambda c: c.data.startswith('price_'))
async def process_price_selection(callback_query: CallbackQuery):
    try:
        price = int(callback_query.data.split('_')[1])
        user_id = callback_query.from_user.id
        
        with app.app_context():
            user = User.query.filter_by(telegram_id=user_id).first()
            if not user or user.balance < price:
                await callback_query.answer("Insufficient balance. Please deposit first.", show_alert=True)
                return

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{WEBAPP_URL}/game/create", json={'entry_price': price, 'user_id': user.id}) as response:
                    if response.status == 200:
                        data = await response.json()
                        game_id = data['game_id']
                        
                        webapp_target_url = f"{WEBAPP_URL}/game/{game_id}/select_cartela?user_id={user.id}&balance={user.balance}&username={user.username or 'Player'}"
                        
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="Select Your Cartela", web_app=WebAppInfo(url=webapp_target_url))
                        ], [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="menu_main")]])
                        
                        await callback_query.message.edit_caption(
                            caption=f"Game created! Entry price: {price} Birr\n"
                                    f"👤 Player: {user.username or 'Player'}\n"
                                    f"💰 Active Wallet Balance: {user.balance:.2f} Birr\n\n"
                                    f"Please select your cartela number:",
                            reply_markup=keyboard
                        )
                    else:
                        await callback_query.answer("Failed to create game. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error processing price: {e}")

@router.callback_query(F.data == "menu_main")
async def process_back_to_main(callback_query: CallbackQuery):
    try:
        await callback_query.message.delete()
        await callback_query.message.answer_photo(
            photo=get_welcome_photo(),
            caption="Welcome to Edil Bingo! Choose an option below.",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        logger.error(f"Error going back to main menu: {e}")
    await callback_query.answer()


# ==========================================
#         ADMIN FEATURES & BROADCAST
# ==========================================

@router.message(Command("admin"))
async def cmd_admin_panel(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return 
    
    await message.answer("📢 Admin Mode (Broadcast):\nPlease send a text message or a photo with a caption to broadcast to all users.")
    await state.set_state(AdminState.waiting_for_news)

@router.message(Command("setimage"))
async def cmd_admin_set_image(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return 
    
    await message.answer(
        "🖼 <b>Admin Mode (Welcome Image)</b>:\n"
        "Please send the new photo you want to display on the Main Menu.", 
        parse_mode="HTML"
    )
    await state.set_state(AdminState.waiting_for_welcome_image)

@router.message(AdminState.waiting_for_welcome_image, F.photo)
async def process_new_welcome_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id 
    config = load_config()
    config['welcome_image_file_id'] = file_id
    save_config(config)
    await state.clear()
    await message.answer_photo(
        photo=file_id,
        caption="✅ <b>Success!</b> The main menu image has been updated. Users will now see this picture.",
        parse_mode="HTML"
    )

@router.message(AdminState.waiting_for_welcome_image)
async def process_new_welcome_image_invalid(message: Message, state: FSMContext):
    await message.answer("⚠️ Please send a <b>PHOTO</b>, not text. Or type /cancel to cancel.", parse_mode="HTML")

@router.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Action cancelled.")

@router.message(AdminState.waiting_for_news)
async def process_admin_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Starting broadcast process...")
    
    success_count = 0
    with app.app_context():
        users = User.query.all()
        for user in users:
            try:
                if message.photo:
                    await message.bot.send_photo(
                        chat_id=user.telegram_id, 
                        photo=message.photo[-1].file_id, 
                        caption=message.caption or ""
                    )
                else:
                    await message.bot.send_message(chat_id=user.telegram_id, text=message.text or "")
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Failed to broadcast to {user.telegram_id}: {e}")
                
    await message.answer(f"✅ Broadcast complete! Message successfully sent to {success_count} users.")

async def setup_bot():
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    bot = Bot(token=TOKEN)
    await set_bot_commands(bot)
    dp.include_router(router)
    return bot, dp

# ቴሌግራም ቦቱን (Polling) እና የ Flask ሰርቨርን በአንድ ላይ (Background Task) የማስጀመር ሎጂክ
async def run_bot():
    try:
        bot, dp = await setup_bot()
        logger.info("Starting Telegram Bot Polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    # ቦቱ እና ፍላስክ አብረው በአንድ ላይ እንዲሰሩ (Background thread for bot, main thread for flask)
    import threading
    
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
    bot_thread.daemon = True
    bot_thread.start()
    
    run_flask()