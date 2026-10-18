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

def get_or_create_user(telegram_id, username, referrer_id=None):
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(
            id=telegram_id,
            telegram_id=telegram_id,
            username=username or f"Player_{telegram_id}",
            balance=0.0,
            bonus_balance=20.0, # 20 Birr registration bonus
            coin=0,
            is_blocked=False,
            referrer_id=referrer_id
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"New user registered via Telegram bot: {telegram_id} ({username})")
    return user

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
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        referrer_id = int(args[0]) if args else None

        with app.app_context():
            get_or_create_user(user_id, username, referrer_id)

        try:
            await message.answer_photo(
                photo=get_welcome_photo(),
                caption="Welcome to Edil Bingo! Choose an option below.",
                reply_markup=get_main_menu()
            )
        except Exception as photo_err:
            logger.warning(f"Could not send welcome photo, sending text instead: {photo_err}")
            await message.answer(
                "Welcome to Edil Bingo! Choose an option below.",
                reply_markup=get_main_menu()
            )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer("Sorry, there was an error. Please try again later.")

@router.message(Command("register"))
@router.callback_query(F.data == "menu_register")
async def process_register_command_or_callback(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id
    username = event.from_user.username or event.from_user.first_name
    message = event.message if isinstance(event, CallbackQuery) else event
    try:
        with app.app_context():
            user = get_or_create_user(user_id, username)
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
async def process_phone_number(message: Message, state: FSMContext):
    await state.clear()
    if not message.contact or message.contact.user_id != message.from_user.id:
        await message.answer("Please share your own contact information.")
        return

    try:
        with app.app_context():
            user_id = message.from_user.id
            username = message.from_user.username or message.from_user.first_name
            user = get_or_create_user(user_id, username)

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
            
            try:
                await message.answer_photo(
                    photo=get_welcome_photo(),
                    caption="Welcome to Edil Bingo! Choose an option below.",
                    reply_markup=get_main_menu()
                )
            except Exception:
                await message.answer(
                    "Welcome to Edil Bingo! Choose an option below.",
                    reply_markup=get_main_menu()
                )
    except Exception as e:
        logger.error(f"Error processing phone number: {e}")

@router.message(Command("balance"))
@router.callback_query(F.data == "menu_balance")
async def process_balance_command_or_callback(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id
    username = event.from_user.username or event.from_user.first_name
    message = event.message if isinstance(event, CallbackQuery) else event
    with app.app_context():
        user = get_or_create_user(user_id, username)
        name = user.username or username or "Unknown"
        phone = user.phone or "Not provided"
        
        details_html = (
            "<b>Account Details</b>\n"
            "<pre><code class=\"language-copy\">"
            f"Name:           {name}\n"
            f"Phone:          {phone}\n"
            f"Main Balance:   {user.balance:.2f} Birr\n"
            f"Bonus Balance:  {user.bonus_balance:.2f} Birr\n"
            f"Coins:          {user.coin} Coins"
            "</code></pre>"
        )
        await message.answer(details_html, parse_mode="HTML")
    if isinstance(event, CallbackQuery):
        await event.answer()

@router.message(Command("playbingo"))
@router.callback_query(F.data == "menu_play_bingo")
async def process_play_bingo_command_or_callback(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id
    username = event.from_user.username or event.from_user.first_name
    message = event.message if isinstance(event, CallbackQuery) else event
    
    with app.app_context():
        user = get_or_create_user(user_id, username)

    webapp_lobby_url = f"{WEBAPP_URL}/?user_id={user_id}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Open Edil Bingo Lobby", web_app=WebAppInfo(url=webapp_lobby_url))
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
        ]
    ])
    
    caption = "🍀 Click below to open the Edil Bingo Lobby and choose your game room! 🎮"

    if isinstance(event, CallbackQuery):
        try:
            await message.edit_caption(caption=caption, reply_markup=keyboard)
        except Exception:
            await message.answer(caption, reply_markup=keyboard)
        await event.answer()
    else:
        try:
            await message.answer_photo(
                photo=get_welcome_photo(),
                caption=caption,
                reply_markup=keyboard
            )
        except Exception:
            await message.answer(caption, reply_markup=keyboard)

@router.callback_query(F.data == "menu_instruction")
async def process_menu_instruction(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "📖 <b>Edil Bingo Instructions</b>:\n\n"
        "1. Select a room according to your stake (10, 20, 50, 100 Birr).\n"
        "2. Choose up to 4 Cartelas (1-200).\n"
        "3. Wait for the countdown and game to start.\n"
        "4. Mark called numbers and claim Bingo to win the prize pool!\n"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")]])
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(F.data == "menu_invite")
async def process_menu_invite(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback_query.from_user.id
    bot_info = await callback_query.bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
    text = (
        "✉️ <b>Invite Friends & Earn!</b>\n\n"
        f"Share your referral link with friends:\n<code>{referral_link}</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")]])
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()


# ==========================================
#   TELEBIRR & CBE BIRR DEPOSIT LOGIC (ጥያቄ ቁጥር 7)
# ==========================================

@router.message(Command("deposit"))
@router.callback_query(F.data == "menu_deposit")
async def process_deposit_command_or_callback(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id
    username = event.from_user.username or event.from_user.first_name
    message = event.message if isinstance(event, CallbackQuery) else event
    with app.app_context():
        get_or_create_user(user_id, username)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Telebirr", callback_data="dep_method_telebirr"),
            InlineKeyboardButton(text="🏦 CBE Birr", callback_data="dep_method_cbe")
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
        ]
    ])

    caption = "💳 <b>Deposit Funds (ዲፖዚት)</b>\n\nChoose your preferred payment method (Telebirr or CBE Birr):"
    if isinstance(event, CallbackQuery):
        try:
            await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        try:
            await message.answer_photo(photo=get_welcome_photo(), caption=caption, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
    
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
    
    try:
        await callback_query.message.edit_caption(
            caption=f"Selected Method: <b>{method}</b>\n\n"
                    "💰 Enter the amount you want to deposit (in birr):",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback_query.answer()

@router.message(UserState.waiting_for_deposit_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < 10:
            await message.answer("⚠️ Minimum deposit amount is 10 birr. Please enter a valid amount:")
            return

        await state.update_data(deposit_amount=amount)
        data = await state.get_data()
        method = data.get("deposit_method")

        await state.set_state(UserState.waiting_for_deposit_reference)
        account_info = "0911111111 (Telebirr Merchant)" if method == "Telebirr" else "1000123456 - Edil Bingo (CBE Birr)"
        
        await message.answer(
            f"✅ Amount: <b>{amount} birr</b> via <b>{method}</b> confirmed.\n\n"
            f"1. Transfer the money to our merchant account:\n"
            f"   👉 <b>{account_info}</b>\n\n"
            f"2. Send your transaction reference number:",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Please enter a valid numerical amount.")

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
        user.balance += amount
        transaction = Transaction(
            user_id=user.id,
            type='deposit',
            amount=amount,
            payment_method=method,
            transaction_id=ref_text,
            status='completed',
            completed_at=datetime.utcnow()
        )
        db.session.add(transaction)
        db.session.commit()

        await message.answer(
            f"✅ <b>Deposit Successful & Credited!</b>\n\n"
            f"Method: {method}\n"
            f"Amount: {amount:.2f} birr\n"
            f"New Balance: {user.balance:.2f} birr",
            parse_mode="HTML"
        )


# ==========================================
#         TELEBIRR & CBE BIRR WITHDRAWAL LOGIC (ጥያቄ ቁጥር 7)
# ==========================================

@router.message(Command("withdraw"))
@router.callback_query(F.data == "menu_withdraw")
async def process_withdraw_command_or_callback(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id
    message = event.message if isinstance(event, CallbackQuery) else event
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if not user:
            user = get_or_create_user(user_id, event.from_user.username)
        
        if user.balance < 50:
            text = f"⚠️ Insufficient Main Balance for withdrawal. Your Balance is {user.balance:.2f} birr."
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

    caption = f"💳 <b>Withdraw Funds (ዊዝድራው)</b>\n\nYour Main Balance: <b>{user.balance:.2f} Birr</b>\nSelect your payout method:"
    if isinstance(event, CallbackQuery):
        try:
            await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        try:
            await message.answer_photo(photo=get_welcome_photo(), caption=caption, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
    
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

    try:
        await callback_query.message.edit_caption(
            caption=f"Selected Method: <b>{method}</b>\n\n"
                    f"💰 Your Balance: <b>{max_bal:.2f} birr</b>\nEnter amount to withdraw:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback_query.answer()

@router.message(UserState.waiting_for_withdraw_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        with app.app_context():
            user = User.query.filter_by(telegram_id=message.from_user.id).first()
            if amount > user.balance:
                await message.answer(f"⚠️ Insufficient balance. You have {user.balance:.2f} birr.")
                return

        await state.update_data(withdraw_amount=amount)
        data = await state.get_data()
        method = data.get("withdraw_method")
        
        await state.set_state(UserState.waiting_for_withdraw_phone)
        account_prompt = "📱 Please enter your <b>Telebirr phone number</b>:" if method == "Telebirr" else "🏦 Please enter your <b>CBE account number</b>:"
        
        await message.answer(f"✅ Amount: <b>{amount} birr</b> via <b>{method}</b>.\n\n{account_prompt}", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Please enter a valid amount.")

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
            payment_method=method,
            status='pending',
            withdrawal_phone=payout_account
        )
        db.session.add(transaction)
        db.session.commit()
        tx_id = transaction.id

    await message.answer("✅ Withdrawal request submitted successfully. Waiting for admin approval.")

    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_wd_approve_{tx_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_wd_reject_{tx_id}")
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 <b>New Withdrawal Request!</b>\n\n👤 User: @{username}\n💰 Amount: <b>{amount} birr</b>\n📱 Method: <b>{method}: {payout_account}</b>",
                parse_mode="HTML",
                reply_markup=admin_keyboard
            )
        except Exception:
            pass


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
            report_text += f"👤 {u.username} | 📱 {u.phone} | 💰 Main: {u.balance:.2f}\n"

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
            await callback_query.answer("Already processed.", show_alert=True)
            return

        user = User.query.get(tx.user_id)
        if action == "approve":
            tx.status = 'completed'
            tx.completed_at = datetime.utcnow()
            db.session.commit()
            await callback_query.message.edit_text(f"✅ Withdrawal Approved for user {user.telegram_id}.")
        else:
            tx.status = 'rejected'
            user.balance += abs(tx.amount)
            db.session.commit()
            await callback_query.message.edit_text(f"❌ Withdrawal Rejected & Refunded.")
    await callback_query.answer()


@router.callback_query(F.data == "menu_main")
async def process_back_to_main(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback_query.message.delete()
        await callback_query.message.answer_photo(
            photo=get_welcome_photo(),
            caption="Welcome to Edil Bingo! Choose an option below.",
            reply_markup=get_main_menu()
        )
    except Exception:
        pass
    await callback_query.answer()


# ==========================================
#             BOT ENTRYPOINT
# ==========================================

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    await set_bot_commands(bot)
    logger.info("Starting Aiogram bot polling...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())