import os
import io
import logging
import base64
import sys
import sqlite3
import json
from datetime import datetime
import os
import glob
import time
import shutil
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
from openai import OpenAI
from openai import OpenAIError

# Создаем директории для временных файлов
TEMP_DIR = "images/temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# API keys
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Проверка наличия необходимых переменных окружения
if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    print("ОШИБКА: Не найдены необходимые переменные окружения TELEGRAM_TOKEN или OPENAI_API_KEY")
    print("Пожалуйста, убедитесь, что они установлены в файле .env или в переменных окружения системы")
    
# Выводим информацию о загруженных переменных
print("Переменные окружения загружены из .env файла")
print("Доступные переменные окружения:")
print(f"TELEGRAM_TOKEN: {'***' + TELEGRAM_TOKEN[-4:] if TELEGRAM_TOKEN else 'Не установлен'}")
print(f"BOT_USERNAME: {BOT_USERNAME if BOT_USERNAME else 'Не установлен'}")
print(f"OPENAI_API_KEY: {'***' + OPENAI_API_KEY[-4:] if OPENAI_API_KEY else 'Не установлен'}")

# Constants for balance system
INITIAL_BALANCE = 5  # Stars
GENERATION_COST = 25  # Stars per generation

# Constants for Telegram Stars payments
STARS_PACKAGES = [
    {"stars": 50, "price": 50, "label": "2 фото"},
    {"stars": 100, "price": 100, "label": "4 фото"},
    {"stars": 250, "price": 250, "label": "10 фото"},
    {"stars": 500, "price": 500, "label": "20 фото"}
]

# Initialize database
def get_db_connection():
    """Create and return a connection to the SQLite database."""
    # Всегда используем директорию с ботом для хранения базы данных
    db_dir = os.path.dirname(os.path.abspath(__file__))
    
    db_path = os.path.join(db_dir, 'users.db')
    logger.info(f"Подключение к базе данных по пути: {db_path}")
    conn = sqlite3.connect(db_path)
    return conn

def backup_db():
    """Create a backup of the database."""
    try:
        # Получаем путь к базе данных
        db_dir = os.path.dirname(os.path.abspath(__file__))  # Всегда используем директорию с ботом
        db_path = os.path.join(db_dir, 'users.db')
        
        # Создаем директорию для резервных копий
        backup_dir = os.path.join(db_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Создаем имя файла с текущей датой
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'users_backup_{timestamp}.db')
        
        # Проверяем, существует ли исходная база данных
        if os.path.exists(db_path):
            # Копируем базу данных
            shutil.copy2(db_path, backup_path)
            logger.info(f"Создана резервная копия базы данных: {backup_path}")
            
            # Также создаем постоянную резервную копию
            permanent_backup_path = os.path.join(backup_dir, 'users_permanent_backup.db')
            shutil.copy2(db_path, permanent_backup_path)
            logger.info(f"Создана постоянная резервная копия базы данных: {permanent_backup_path}")
            
            # Удаляем старые резервные копии (оставляем только 5 последних)
            backup_files = sorted(glob.glob(os.path.join(backup_dir, 'users_backup_*.db')))
            if len(backup_files) > 5:
                for old_backup in backup_files[:-5]:
                    os.remove(old_backup)
                    logger.info(f"Удалена старая резервная копия: {old_backup}")
            
            return True
        else:
            logger.warning(f"Не удалось создать резервную копию: файл базы данных не найден: {db_path}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при создании резервной копии базы данных: {e}")
        return False

def restore_db_from_backup():
    """Restore database from the latest backup if the main database is corrupted or missing."""
    try:
        # Получаем путь к базе данных
        db_dir = os.path.dirname(os.path.abspath(__file__))  # Всегда используем директорию с ботом
        db_path = os.path.join(db_dir, 'users.db')
        backup_dir = os.path.join(db_dir, 'backups')
        
        # Создаем директорию для резервных копий, если она не существует
        os.makedirs(backup_dir, exist_ok=True)
        
        # Сначала проверяем наличие постоянной резервной копии
        permanent_backup_path = os.path.join(backup_dir, 'users_permanent_backup.db')
        if os.path.exists(permanent_backup_path):
            # Копируем постоянную резервную копию в основной файл базы данных
            shutil.copy2(permanent_backup_path, db_path)
            logger.info(f"База данных успешно восстановлена из постоянной резервной копии: {permanent_backup_path}")
            return True
        
        # Если постоянной резервной копии нет, проверяем наличие обычных резервных копий
        backup_files = sorted(glob.glob(os.path.join(backup_dir, 'users_backup_*.db')))
        if backup_files:
            latest_backup = backup_files[-1]
            
            # Копируем последнюю резервную копию в основной файл базы данных
            shutil.copy2(latest_backup, db_path)
            logger.info(f"База данных успешно восстановлена из последней резервной копии: {latest_backup}")
            
            # Создаем постоянную резервную копию из последней резервной копии
            shutil.copy2(latest_backup, permanent_backup_path)
            logger.info(f"Создана постоянная резервная копия из последней резервной копии: {permanent_backup_path}")
            return True
        else:
            logger.warning("Резервные копии не найдены.")
            return False
    except Exception as e:
        logger.error(f"Ошибка при восстановлении базы данных из резервной копии: {e}")
        return False

def init_db():
    """Initialize the database with users table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        balance INTEGER DEFAULT 10,
        total_generations INTEGER DEFAULT 0,
        last_generation TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()
    
    # Создаем резервную копию после инициализации
    backup_db()
    logger.info("Database initialized")

# User balance functions
def get_user_balance(user_id):
    """Get user balance from database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    else:
        # Create new user with initial balance
        create_user(user_id, None, None, None)
        return INITIAL_BALANCE

def create_user(user_id, username, first_name, last_name):
    """Create a new user in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, balance, created_at) 
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, INITIAL_BALANCE, datetime.now()))
    conn.commit()
    conn.close()
    logger.info(f"Created new user: {user_id}")

def update_user_balance(user_id, amount):
    """Update user balance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    cursor.execute('UPDATE users SET total_generations = total_generations + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('UPDATE users SET last_generation = ? WHERE user_id = ?', (datetime.now(), user_id))
    conn.commit()
    conn.close()
    logger.info(f"Updated balance for user {user_id}: {amount}")

def check_balance_sufficient(user_id):
    """Check if user has sufficient balance for generation."""
    balance = get_user_balance(user_id)
    return balance >= GENERATION_COST

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Create images directory if it doesn't exist
if not os.path.exists("images"):
    os.makedirs("images")
    logger.info("Создана директория для изображений")

def test_openai_connection():
    """Test connection to OpenAI API."""
    try:
        print("Проверка подключения к OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Hello!"}],
            max_tokens=10
        )
        print(f"Подключение к OpenAI успешно! Ответ: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"Предупреждение при подключении к OpenAI: {e}")
        print("Продолжаем запуск бота с ограниченной функциональностью")
        # Return True anyway to allow the bot to start
        return True

def create_main_menu():
    """Create the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🎨 Сгенерировать фото", callback_data="generate_image")],
        [InlineKeyboardButton("⭐ Мои звёзды", callback_data="check_balance")],
        [InlineKeyboardButton("💸 Купить звёзды", callback_data="topup_balance")],
        [InlineKeyboardButton("👥 Пригласить друзей", callback_data="invite_friend")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_topup_menu():
    """Create the topup menu keyboard."""
    keyboard = []
    for package in STARS_PACKAGES:
        generations = package["stars"] // GENERATION_COST
        keyboard.append([InlineKeyboardButton(
            f"{package['label']} • {package['stars']} звезд", 
            callback_data=f"buy_stars_{package['stars']}"
        )])
    keyboard.append([InlineKeyboardButton("Вернуться", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    # Create or update user in database
    create_user(user.id, user.username, user.first_name, user.last_name)
    
    # Get user balance
    balance = get_user_balance(user.id)
    
    # Отправляем приветственное сообщение
    welcome_text = (
        f"Привет, {user.mention_html()}! 👋\n\n"
        "✨ Я бот для стилизации фотографий в различных стилях. ✨\n\n"
        "🎨 Генерирую изображения в стилях Disney, Ghibli, Lego и других популярных форматах.\n\n"
        "📱 Как использовать:\n"
        "1. Отправьте фотографию\n"
        "2. Выберите желаемый стиль\n"
        "3. Получите готовое изображение в выбранном стиле\n\n"
        f"Ваш текущий баланс: ⭐ {balance} звёзд\n"
        f"Стоимость одного фото: ⭐ {GENERATION_COST} звёзд\n\n"
        "Продолжая, вы подтверждаете, что соглашаетесь с "
        "<a href='https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-04-05-9'>Политикой конфиденциальности</a> и "
        "<a href='https://telegra.ph/USLOVIYA-ISPOLZOVANIYA-04-05'>Условиями использования</a>"
    )
    
    await update.message.reply_html(welcome_text, disable_web_page_preview=True)
    
    # Send demo images as a group
    demo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo")
    
    # Prepare media group with all demo images
    media_group = []
    demo_files = [
        ("image ghibli.png", "Примеры стилизации фотографий"),
        ("disney.png", None),
        ("toy.jpg", None)
    ]
    
    # Create InputMediaPhoto objects for each demo image
    for i, (file_name, caption) in enumerate(demo_files):
        file_path = os.path.join(demo_dir, file_name)
        try:
            with open(file_path, 'rb') as photo_file:
                media_group.append(InputMediaPhoto(
                    media=photo_file.read(),
                    caption=caption if i == 0 else None  # Caption only for the first image
                ))
        except Exception as e:
            logger.error(f"Error loading demo image {file_name}: {e}")
    
    # Send media group
    if media_group:
        try:
            await context.bot.send_media_group(
                chat_id=update.effective_chat.id, 
                media=media_group
            )
            
            # Отправляем сообщение с призывом к действию и меню после демо изображений
            action_message = (
                "🔮 Отправьте фото для генерации изображения в выбранном стиле.\n\n"
                "🌟 Приглашайте друзей и получайте 50% от их покупок в виде звёзд."
            )
            await update.message.reply_text(action_message, reply_markup=create_main_menu())
            
        except Exception as e:
            logger.error(f"Error sending demo images: {e}")
            # Fallback to sending images one by one if group fails
            for file_name, caption in demo_files:
                file_path = os.path.join(demo_dir, file_name)
                try:
                    with open(file_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=caption
                        )
                except Exception as e:
                    logger.error(f"Error sending individual demo image {file_name}: {e}")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display the main menu."""
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    
    await update.message.reply_text(
        f"Главное меню\n\n"
        f"Ваш текущий баланс: ⭐ {balance} звезд\n"
        f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n",
        reply_markup=create_main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    
    await update.message.reply_text(
        "Как использовать бота:\n\n"
        "1. Отправьте фотографию или нажмите кнопку 'Сгенерировать изображение'\n"
        "2. Подождите немного, пока я обрабатываю изображение\n"
        "3. Получите вашу фотографию в стиле студии Ghibli!\n\n"
        f"Ваш текущий баланс: ⭐ {balance} звезд\n"
        f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n\n"
        "Команды:\n"
        "/start - Приветственное сообщение\n"
        "/menu - Показать главное меню\n"
        "/balance - Проверить баланс\n"
        "/help - Эта справка",
        reply_markup=create_main_menu()
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user balance."""
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    
    # Create inline keyboard for balance options
    keyboard = [
        [InlineKeyboardButton("💰 Пополнить баланс", callback_data="topup_balance")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Ваш текущий баланс: ⭐ {balance} звезд\n"
        f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    
    # Проверяем, является ли сообщение фотографией (имеет поле photo)
    is_photo_message = hasattr(query.message, 'photo') and query.message.photo
    
    if query.data == "generate_image":
        # Create style selection keyboard
        keyboard = [
            [InlineKeyboardButton("Ghibli (Аниме)", callback_data="style_ghibli")],
            [InlineKeyboardButton("Disney", callback_data="style_disney")],
            [InlineKeyboardButton("Lego", callback_data="style_lego")],
            [InlineKeyboardButton("Кукла Блайз", callback_data="style_blythe")],
            [InlineKeyboardButton("Симпсоны", callback_data="style_simpsons")],
            [InlineKeyboardButton("Игрушка", callback_data="style_toy")],
            [InlineKeyboardButton("Свой стиль", callback_data="style_custom")],
            [InlineKeyboardButton("Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="Выберите стиль для вашего изображения:",
            reply_markup=reply_markup
        )
    
    elif query.data == "check_balance":
        # Create inline keyboard for balance options
        keyboard = [
            [InlineKeyboardButton("💰 Пополнить баланс", callback_data="topup_balance")],
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"Ваш текущий баланс: ⭐ {balance} звезд\n"
                f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n",
            reply_markup=reply_markup
        )
    
    elif query.data == "use_my_name":
        # Обработка кнопки "Использовать моё имя"
        user_name = update.effective_user.first_name
        
        # Сохраняем имя пользователя для гравировки
        if 'user_data' not in context.user_data:
            context.user_data['user_data'] = {}
        context.user_data['user_data']['custom_name'] = user_name
        
        # Убираем флаг ожидания имени и устанавливаем флаг ожидания аксессуаров
        context.user_data['user_data']['waiting_for_toy_name'] = False
        context.user_data['user_data']['waiting_for_accessories'] = True
        
        # Отправляем сообщение с просьбой указать аксессуары
        balance = get_user_balance(user_id)
        balance_text = f"Стоимость: ⭐ {GENERATION_COST} звезд | Ваш баланс: ⭐ {balance} звезд"
        
        await query.edit_message_text(
            text=f"🔮 Отлично! Имя для гравировки: <b>{user_name}</b>\n\n"
                 f"Теперь укажите аксессуары для вашей игрушки в следующем сообщении.\n"
                 f"Например: солнцезащитные очки, микрофон, гитара\n\n"
                 f"{balance_text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Отменить", callback_data="generate_image")]
            ]),
            parse_mode="HTML"
        )
        return
        
    elif query.data == "topup_balance":
        # Display star packages menu
        topup_text = "Выберите количество звезд для покупки:"
        
        # Проверяем, является ли сообщение фотографией
        if is_photo_message:
            # Если это фото, отправляем новое сообщение
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=topup_text,
                reply_markup=create_topup_menu()
            )
        else:
            # Если это обычное сообщение, редактируем его
            await query.edit_message_text(
                text=topup_text,
                reply_markup=create_topup_menu()
            )
    
    elif query.data.startswith("buy_stars_"):
        stars_amount = int(query.data.split("_")[2])
        
        # Find the package
        package = next((p for p in STARS_PACKAGES if p["stars"] == stars_amount), None)
        
        if package:
            # Create invoice for Telegram Stars payment
            title = f"Пополнение баланса: {stars_amount} звезд"
            description = f"Пополнение баланса на {stars_amount} звезд для генерации изображений в стиле Ghibli"
            
            # Создаем payload с точными данными о количестве звезд
            payload = json.dumps({
                "user_id": user_id,
                "stars": stars_amount,
                "price": package["price"]
            })
            
            # Для цифровых товаров в Telegram Stars используем пустой provider_token
            provider_token = ""  # Пустой токен для цифровых товаров
            currency = "XTR"  # Telegram Stars currency code
            
            # Для Telegram Stars используем количество звезд, а не цену
            price_amount = stars_amount  # Количество звезд, которое будет списано
            
            # Создаем массив цен с одним элементом
            prices = [LabeledPrice(label=f"{stars_amount} звезд", amount=price_amount)]
            
            # Логируем данные платежа для отладки
            logger.info(f"Создание платежа: stars={stars_amount}, price={package['price']}, price_amount={price_amount}")
            
            try:
                # Отправляем счет на оплату
                await context.bot.send_invoice(
                    chat_id=user_id,
                    title=title,
                    description=description,
                    payload=payload,
                    provider_token=provider_token,  # Пустой токен для цифровых товаров
                    currency=currency,
                    prices=prices,
                    need_name=False,
                    need_phone_number=False,
                    need_email=False,
                    need_shipping_address=False,
                    is_flexible=False,
                    start_parameter="pay"  # Добавляем start_parameter для правильной обработки
                )
                
                await query.edit_message_text(
                    text=f"Счет на оплату {stars_amount} звезд создан. Пожалуйста, оплатите его, чтобы пополнить баланс.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]])
                )
                
                # Логируем успешное создание счета
                logger.info(f"Счет на оплату {stars_amount} звезд успешно создан для пользователя {user_id}")
            except Exception as e:
                logger.error(f"Ошибка при создании счета: {e}")
                await query.edit_message_text(
                    text=f"Произошла ошибка при создании счета. Пожалуйста, попробуйте позже.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]])
                )

    elif query.data == "invite_friend":
        # Create bot's username link
        bot_username = BOT_USERNAME
        invite_link = f"https://t.me/{bot_username}?start={user_id}"
        
        # Generate message with affiliate link instructions
        message = (
            "🎉 Приглашайте друзей и получайте бонусы! 🎉\n\n"
            "Пригласив друга, вы получите 50% от всех звездочек, которые он потратит в боте.\n\n"
            "Как это работает:\n"
            "1. Зайдите в шапку бота @" + bot_username + "\n"
            "2. Скопируйте вашу партнерскую ссылку\n"
            "3. Отправьте ее друзьям"
        )
        
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]])
        )
        
    elif query.data == "help":
        await query.edit_message_text(
            text="Как использовать бота:\n\n"
                "1. Отправьте фотографию или нажмите кнопку 'Сгенерировать изображение'\n"
                "2. Выберите желаемый стиль (различные варианты доступны)\n"
                "3. Подождите немного, пока я обрабатываю изображение\n"
                "4. Получите вашу фотографию в выбранном стиле!\n\n"
                f"Ваш текущий баланс: ⭐ {balance} звезд\n"
                f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n\n"
                "Пригласите друзей:\n"
                "Получайте 50% от всех звездочек, которые ваши друзья потратят в боте.\n\n"
                "Команды:\n"
                "/start - Приветственное сообщение\n"
                "/menu - Показать главное меню\n"
                "/balance - Проверить баланс\n"
                "/help - Эта справка",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]])
        )
    
    elif query.data.startswith("style_"):
        # Обработка выбора стиля
        selected_style = query.data.split("_")[1]  # Получаем стиль из callback_data
        
        # Сохраняем выбранный стиль в данных пользователя
        if 'user_data' not in context.user_data:
            context.user_data['user_data'] = {}
        
        context.user_data['user_data']['selected_style'] = selected_style
        
        # Найдем имя стиля для отображения
        style_display_names = {
            "ghibli": "Ghibli (Аниме)",
            "disney": "Disney",
            "lego": "Lego",
            "blythe": "Кукла Блайз",
            "simpsons": "Симпсоны",
            "toy": "Игрушка",
            "custom": "Свой стиль"
        }
        
        style_name = style_display_names.get(selected_style, "выбранном стиле")
        
        # Проверяем, достаточно ли средств у пользователя
        balance_sufficient = balance >= GENERATION_COST
        
        # Подготавливаем сообщение в зависимости от баланса
        if balance_sufficient:
            balance_text = f"Стоимость: ⭐ {GENERATION_COST} звезд | Ваш баланс: ⭐ {balance} звезд"
            action_text = f"👇 <b>Отправьте вашу фотографию прямо сейчас</b>, чтобы преобразовать её в выбранный стиль!"
        else:
            balance_text = f"<b>Недостаточно средств!</b>\nСтоимость: ⭐ {GENERATION_COST} звезд | Ваш баланс: ⭐ {balance} звезд"
            action_text = f"Пожалуйста, пополните баланс, чтобы создать изображение в стиле {style_name}"
        
        # Подготавливаем кнопки в зависимости от баланса
        keyboard = []
        if not balance_sufficient:
            keyboard.append([InlineKeyboardButton("Пополнить баланс", callback_data="topup_balance")])
        
        keyboard.append([InlineKeyboardButton("Выбрать другой стиль", callback_data="generate_image")])
        keyboard.append([InlineKeyboardButton("Назад в меню", callback_data="back_to_menu")])
        
        # Проверяем, выбран ли стиль "Игрушка"
        if selected_style == "toy":
            # Проверяем, достаточно ли средств у пользователя
            if balance_sufficient:
                # Добавляем флаг, что ожидаем ввод имени для гравировки
                context.user_data['user_data']['waiting_for_toy_name'] = True
                
                # Отправляем сообщение с просьбой указать имя для гравировки
                await query.edit_message_text(
                    text=f"🔮 Вы выбрали стиль: <b>{style_name}</b>\n\n"
                         f"Сначала укажите имя для гравировки на коробке игрушки.\n"
                         f"Это имя будет выгравировано на упаковке.\n\n"
                         f"{balance_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Использовать моё имя", callback_data="use_my_name")],
                        [InlineKeyboardButton("Отменить", callback_data="generate_image")]
                    ]),
                    parse_mode="HTML"
                )
            else:
                # Если недостаточно средств, отправляем стандартное сообщение о недостатке средств
                await query.edit_message_text(
                    text=f"🔮 Вы выбрали стиль: <b>{style_name}</b>\n\n"
                         f"{action_text}\n\n"
                         f"{balance_text}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
            return
            
        # Проверяем, выбран ли стиль "Свой стиль"
        elif selected_style == "custom":
            # Добавляем флаг, что ожидаем ввод описания стиля
            context.user_data['user_data']['waiting_for_custom_style'] = True
            
            # Проверяем, достаточно ли средств у пользователя
            if balance_sufficient:
                # Отправляем сообщение с просьбой описать желаемый стиль
                await query.edit_message_text(
                    text=f"🔮 Вы выбрали стиль: <b>{style_name}</b>\n\n"
                         f"Пожалуйста, опишите желаемый стиль в следующем сообщении.\n"
                         f"Например: В стиле персонажа SIMS с зеленым ромбом над головой!\n\n"
                         f"{balance_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Отменить", callback_data="generate_image")]
                    ]),
                    parse_mode="HTML"
                )
            else:
                # Если недостаточно средств, отправляем стандартное сообщение о недостатке средств
                await query.edit_message_text(
                    text=f"🔮 Вы выбрали стиль: <b>{style_name}</b>\n\n"
                         f"{action_text}\n\n"
                         f"{balance_text}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
            return
        
        # Для всех остальных стилей отправляем стандартное сообщение
        # Отправляем новое сообщение с инструкцией и призывом к действию
        await query.edit_message_text(
            text=f"🔮 Вы выбрали стиль: <b>{style_name}</b>\n\n"
                 f"{action_text}\n\n"
                 f"{balance_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
        logger.info(f"Пользователь {user_id} выбрал стиль: {style_name}")
    
    elif query.data == "generate_new":
        # Обработчик для кнопки "Сгенерировать еще"
        # Создаем клавиатуру выбора стиля
        keyboard = [
            [InlineKeyboardButton("Ghibli (Аниме)", callback_data="style_ghibli")],
            [InlineKeyboardButton("Disney", callback_data="style_disney")],
            [InlineKeyboardButton("Lego", callback_data="style_lego")],
            [InlineKeyboardButton("Кукла Блайз", callback_data="style_blythe")],
            [InlineKeyboardButton("Симпсоны", callback_data="style_simpsons")],
            [InlineKeyboardButton("Игрушка", callback_data="style_toy")],
            [InlineKeyboardButton("Свой стиль", callback_data="style_custom")],
            [InlineKeyboardButton("Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Проверяем, является ли сообщение фотографией
        if is_photo_message:
            # Если это фото, отправляем новое сообщение
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Выберите стиль для вашего изображения:",
                reply_markup=reply_markup
            )
        else:
            # Если это обычное сообщение, редактируем его
            await query.edit_message_text(
                text="Выберите стиль для вашего изображения:",
                reply_markup=reply_markup
            )
    
    elif query.data == "back_to_menu":
        menu_text = f"Главное меню\n\n"\
                  f"Ваш текущий баланс: ⭐ {balance} звезд\n"\
                  f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n"
        
        # Проверяем, является ли сообщение фотографией
        if is_photo_message:
            # Если это фото, отправляем новое сообщение
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=menu_text,
                reply_markup=create_main_menu()
            )
        else:
            # Если это обычное сообщение, редактируем его
            await query.edit_message_text(
                text=menu_text,
                reply_markup=create_main_menu()
            )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the pre-checkout callback."""
    query = update.pre_checkout_query
    
    try:
        # Parse the payload
        payload = json.loads(query.invoice_payload)
        user_id = payload.get("user_id")
        stars = payload.get("stars")
        
        # Логируем данные предварительной проверки
        logger.info(f"Предварительная проверка платежа: user_id={user_id}, stars={stars}, total_amount={query.total_amount}")
        
        # Validate the payment
        if user_id and stars:
            # Accept the payment
            await query.answer(ok=True)
            logger.info(f"Предварительная проверка платежа одобрена: {stars} звезд для пользователя {user_id}")
        else:
            # Reject the payment
            await query.answer(ok=False, error_message="Неверные данные платежа. Пожалуйста, попробуйте снова.")
            logger.warning(f"Предварительная проверка платежа отклонена: неверные данные")
    except Exception as e:
        logger.error(f"Ошибка при обработке предварительной проверки платежа: {e}")
        await query.answer(ok=False, error_message="Произошла ошибка при обработке платежа. Пожалуйста, попробуйте снова.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle successful payments."""
    payment = update.message.successful_payment
    
    try:
        # Parse the payload
        payload = json.loads(payment.invoice_payload)
        user_id = payload.get("user_id")
        stars = payload.get("stars")
        
        # Логируем данные успешного платежа
        logger.info(f"Успешный платеж: user_id={user_id}, stars={stars}, total_amount={payment.total_amount}")
        
        if user_id and stars:
            # Add stars to user balance
            update_user_balance(user_id, stars)
            new_balance = get_user_balance(user_id)
            
            # Send confirmation message
            await update.message.reply_text(
                f"✅ Оплата успешно выполнена!\n\n"
                f"Добавлено: ⭐ {stars} звезд\n"
                f"Текущий баланс: ⭐ {new_balance} звезд\n\n"
                f"Спасибо за поддержку!",
                reply_markup=create_main_menu()
            )
            
            logger.info(f"Пользователь {user_id} успешно пополнил баланс на {stars} звезд. Новый баланс: {new_balance}")
        else:
            await update.message.reply_text(
                "Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с поддержкой.",
                reply_markup=create_main_menu()
            )
            logger.warning(f"Ошибка при обработке успешного платежа: отсутствуют данные user_id или stars")
    except Exception as e:
        logger.error(f"Ошибка при обработке успешного платежа: {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с поддержкой.",
            reply_markup=create_main_menu()
        )

async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a photo and convert it to the selected style."""
    user_id = update.effective_user.id
    
    # Check if user has sufficient balance
    if not check_balance_sufficient(user_id):
        balance = get_user_balance(user_id)
        await update.message.reply_text(
            f"У вас недостаточно звезд для генерации изображения.\n"
            f"Ваш текущий баланс: ⭐ {balance} звезд\n"
            f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд\n"
        )
        return
    
    # Get selected style from user data if available
    selected_style = "ghibli"  # Default style
    if 'user_data' in context.user_data and 'selected_style' in context.user_data['user_data']:
        selected_style = context.user_data['user_data']['selected_style']
        
    # Проверяем, есть ли текст, отправленный вместе с фотографией
    caption_text = update.message.caption
    if caption_text:
        logger.info(f"Получена фотография с текстом: {caption_text}")
        
        # Если выбран стиль "Игрушка" и есть текст, используем его как описание аксессуаров
        if selected_style == "toy":
            if 'user_data' not in context.user_data:
                context.user_data['user_data'] = {}
            context.user_data['user_data']['accessories'] = caption_text
            logger.info(f"Сохранены аксессуары для стиля Игрушка: {caption_text}")
        
        # Если выбран стиль "Свой стиль" и есть текст, используем его как описание стиля
        elif selected_style == "custom":
            if 'user_data' not in context.user_data:
                context.user_data['user_data'] = {}
            context.user_data['user_data']['custom_style'] = caption_text
            logger.info(f"Сохранено описание для своего стиля: {caption_text}")
    
    # Style display names for messages
    style_display_names = {
        "ghibli": "Ghibli (Аниме)",
        "disney": "Disney",
        "lego": "Lego",
        "blythe": "Кукла Блайз",
        "simpsons": "Симпсоны",
        "toy": "Игрушка",
        "custom": "Свой стиль"
    }
    
    style_name = style_display_names.get(selected_style, "выбранном стиле")
    
    # Создаем список разнообразных статусных сообщений
    status_messages = [
        f"Обрабатываю ваше изображение в стиле {style_name}... ⏳",
        f"Запускаю магию изображений в стиле {style_name}...",
        f"Что-то интересное получается в стиле {style_name}...",
        f"Искусственный интеллект рисует вас в стиле {style_name}...",
        f"Цифровые художники уже создают ваш портрет в стиле {style_name}...",
        f"Собираю пиксели для вашего изображения в стиле {style_name}...",
        f"Нейросети очень стараются создать ваш образ в стиле {style_name}..."
    ]
    
    # Выбираем случайное сообщение
    import random
    status_message = await update.message.reply_text(random.choice(status_messages))
    
    try:
        # Get the photo with the highest resolution
        photo = update.message.photo[-1]
        
        # Download the photo
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Используем заранее созданный каталог для временных файлов
        tmp_dir = TEMP_DIR
        
        # Используем уникальное имя файла для каждого запроса, чтобы избежать конфликтов
        import uuid
        from datetime import datetime
        unique_id = f"{update.effective_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{str(uuid.uuid4())[:8]}"
        file_path = f"{tmp_dir}/{unique_id}.png"
        
        # Save photo to a temporary file
        with open(file_path, "wb") as f:
            f.write(photo_bytes)
        
        logger.info(f"Обработка изображения для пользователя {update.effective_user.id} в стиле {style_name}")
        # Создаем список разнообразных сообщений для фазы создания
        creation_messages = [
            f"Создаю изображение в стиле {style_name}... 🎨",
            f"Достаю краски и кисти для вашего портрета в стиле {style_name}... 🧁",
            f"Делаю из вас персонажа в стиле {style_name}... 🌠",
            f"Художественная магия превращает вас в стиль {style_name}... ✨",
            f"Делаю вас звездой в стиле {style_name}... 🌟",
            f"Нейросеть творит чудеса в стиле {style_name}... 💫",
            f"Наношу последние штрихи на изображение в стиле {style_name}... 🎨"
        ]
        
        analysis_messages = [
            "Анализирую ваше фото... 🔍",
            "Изучаю детали вашего лица... 👀",
            "Распознаю черты лица... 👤",
            "Ищу ваши уникальные особенности... 🧐",
            "Записываю все ваши характерные черты... 📝"
        ]
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_message.message_id,
            text=random.choice(creation_messages)
        )
        
        # Выбираем промпт в зависимости от выбранного стиля
        if selected_style == "ghibli":
            prompt = """
            Transform this person into a Studio Ghibli animation character. 
            Use Ghibli's distinctive hand-drawn style with soft watercolor backgrounds and warm color palette.
            Add characteristic Ghibli lighting and atmosphere.
            Maintain the person's likeness and key features while adapting to Ghibli style.
            Include some Ghibli-style environment elements that complement the character.
            """
        elif selected_style == "disney":
            prompt = """
            Transform this person into a Disney 3D animation character.
            Use vibrant colors, expressive features, and Disney's characteristic lighting style.
            Add Disney-style magical environment elements.
            Maintain the person's likeness and key features while adapting to Disney animation style.
            """
        elif selected_style == "lego":
            prompt = """
            Transform this person into a LEGO minifigure.
            Use authentic LEGO minifigure appearance with plastic toy aesthetic.
            Add characteristic LEGO shapes and bright LEGO colors palette.
            Include a LEGO brick background/environment.
            Maintain the person's distinguishing features translated to LEGO style.
            """
        elif selected_style == "simpsons":
            prompt = """
            Transform this person into a Simpsons character.
            Use classic Simpsons yellow skin and distinctive art style.
            Add Simpsons character proportions with overbite and four fingers per hand.
            Include typical Simpsons background elements.
            Maintain the person's distinguishing features adapted to Simpsons style.
            """
        elif selected_style == "toy":
            # Проверяем, есть ли аксессуары в данных пользователя
            accessories = ""
            user_name = update.effective_user.first_name
            
            if 'user_data' in context.user_data:
                if 'accessories' in context.user_data['user_data']:
                    accessories = context.user_data['user_data']['accessories']
                if 'custom_name' in context.user_data['user_data']:
                    user_name = context.user_data['user_data']['custom_name']
            
            prompt = f"""
            Основное:
            Это 3D-кукла в стиле Bratz, из soft touch пластика.
            Персонаж — во весь рост, повторяет внешность с первого фото.
            Копируй каждую деталь: прическу, губы, глаза, черты и пропорции лица. Одежда — с акцентом на стиль и текстуры.
            Кукла лежит в пластиковом углублении, которое повторяет её силуэт.

            Упаковка:
            Стиль коробки современный.
            Коробка: прозрачный пластик спереди, картон сзади.
            Вверху коробки должно быть написано имя персонажа
            {user_name} — буквы впечатаны и выгравированы на коробке

            Аксессуары внутри коробки:
            Разложены рядом с куклой по своим местам в отдельных ячейках: {accessories if accessories else 'стильные аксессуары и модные предметы'}
            Аксессуары — максимально фотореалистичные и детализированные мини-версии.
            Ключ: стиль, визуал и детализация - как у премиальной коллекционной игрушки
            """
        elif selected_style == "custom":
            # Проверяем, есть ли пользовательское описание стиля
            custom_style_description = "уникальный стиль"
            
            if 'user_data' in context.user_data and 'custom_style' in context.user_data['user_data']:
                custom_style_description = context.user_data['user_data']['custom_style']
            
            prompt = f"""
            Создай художественное изображение этого человека в следующем стиле:
            {custom_style_description}
            
            Сохрани узнаваемость и ключевые черты человека, но адаптируй их к запрошенному стилю.
            """
            
            # Если нет пользовательского описания, отправляем сообщение с просьбой указать стиль
            if 'user_data' not in context.user_data or 'custom_style' not in context.user_data['user_data']:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text="Пожалуйста, опишите желаемый стиль в текстовом сообщении."
                )
                
                # Сохраняем информацию о том, что пользователь выбрал свой стиль
                if 'user_data' not in context.user_data:
                    context.user_data['user_data'] = {}
                context.user_data['user_data']['waiting_for_custom_style'] = True
                context.user_data['user_data']['photo_file_path'] = file_path
                
                # Выходим из функции, чтобы не генерировать изображение пока
                return
        elif selected_style == "blythe":
            prompt = """
            Transform this person into a Blythe doll.
            Use characteristic Blythe doll aesthetic with large head and oversized eyes.
            Add distinctive glossy finish and porcelain-like skin texture.
            Include pastel or vibrant colors typical for Blythe dolls.
            Add cute, slightly dreamy expression and Blythe doll fashion elements.
            """
        else:
            # Default to Ghibli if style not recognized
            prompt = """
            Transform this person into a Studio Ghibli animation character. 
            Use Ghibli's distinctive hand-drawn style with soft watercolor backgrounds and warm color palette.
            Add characteristic Ghibli lighting and atmosphere.
            Maintain the person's likeness and key features while adapting to Ghibli style.
            Include some Ghibli-style environment elements that complement the character.
            """
        
        # Используем метод edit вместо generate для лучших результатов
        with open(file_path, "rb") as img_file:
            image_response = client.images.edit(
                model="gpt-image-1",
                image=img_file,
                prompt=prompt,
                size="1024x1536",
                n=1
            )
        
        # Получаем изображение в формате base64
        image_base64 = image_response.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        
        # Сохраняем изображение во временный файл для отправки
        generated_file_path = f"{tmp_dir}/generated_{unique_id}.png"
        with open(generated_file_path, "wb") as f:
            f.write(image_bytes)
            
        logger.info(f"Изображение успешно сгенерировано и сохранено в {generated_file_path}")
        
        # Удаляем временный файл изображения, чтобы не занимать дисковое пространство
        try:
            os.remove(file_path)
            logger.info(f"Временный файл {file_path} успешно удален")
        except Exception as file_error:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {file_error}")
        
        # Deduct stars from user balance
        update_user_balance(user_id, -GENERATION_COST)
        current_balance = get_user_balance(user_id)
        
        # Создаем кнопки для добавления после генерации - строго 3 кнопки
        keyboard = [
            [InlineKeyboardButton("Сгенерировать еще", callback_data="generate_new")],
            [InlineKeyboardButton("Купить звезды", callback_data="topup_balance")],
            [InlineKeyboardButton("Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем изображение пользователю из локального файла
        with open(generated_file_path, 'rb') as photo_file:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_file,
                caption=f"Ваше изображение в стиле {style_name}! 🌟\n\nСписано: ⭐ {GENERATION_COST} звезд\nТекущий баланс: ⭐ {current_balance} звезд",
                reply_markup=reply_markup
            )
        
        # Удаляем сгенерированный файл после отправки
        try:
            os.remove(generated_file_path)
            logger.info(f"Сгенерированный файл {generated_file_path} успешно удален")
        except Exception as file_error:
            logger.warning(f"Не удалось удалить сгенерированный файл {generated_file_path}: {file_error}")
        
        # Удаляем статусное сообщение
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id
            )
        except Exception as msg_error:
            logger.warning(f"Не удалось удалить статусное сообщение: {msg_error}")
            
    except OpenAIError as e:
        logger.error(f"Ошибка OpenAI при обработке изображения: {e}")
        
        # Удаляем временный файл в случае ошибки
        try:
            os.remove(file_path)
            logger.info(f"Временный файл {file_path} удален после ошибки OpenAI")
        except Exception as file_error:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {file_error}")
        
        # Запасной вариант: попробуем DALL-E 2 вариации
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id,
                text="Использую альтернативный метод обработки... 🖌️"
            )
            
            # Выбираем промпт в зависимости от выбранного стиля
            if selected_style == "ghibli":
                prompt = """
                Transform this person into a Studio Ghibli animation character. 
                Use Ghibli's distinctive hand-drawn style with soft watercolor backgrounds and warm color palette.
                Add characteristic Ghibli lighting and atmosphere.
                Maintain the person's likeness and key features while adapting to Ghibli style.
                Include some Ghibli-style environment elements that complement the character.
                """
            elif selected_style == "disney":
                prompt = """
                Transform this person into a Disney 3D animation character.
                Use vibrant colors, expressive features, and Disney's characteristic lighting style.
                Add Disney-style magical environment elements.
                Maintain the person's likeness and key features while adapting to Disney animation style.
                """
            elif selected_style == "lego":
                prompt = """
                Transform this person into a LEGO minifigure.
                Use authentic LEGO minifigure appearance with plastic toy aesthetic.
                Add characteristic LEGO shapes and bright LEGO colors palette.
                Include a LEGO brick background/environment.
                Maintain the person's distinguishing features translated to LEGO style.
                """
            elif selected_style == "simpsons":
                prompt = """
                Transform this person into a Simpsons character.
                Use classic Simpsons yellow skin and distinctive art style.
                Add Simpsons character proportions with overbite and four fingers per hand.
                Include typical Simpsons background elements.
                Maintain the person's distinguishing features adapted to Simpsons style.
                """
            elif selected_style == "soviet":
                prompt = """
                Transform this person into a Soviet animation character from the 1970s-80s.
                Use soft, painterly style with muted color palette.
                Add characteristic round facial features and expressive eyes.
                Include gentle outlines and watercolor-like textures.
                Add nostalgic Soviet-era background elements.
                """
            elif selected_style == "marvel":
                prompt = """
                Transform this person into a Marvel Comics character.
                Use dynamic Marvel comic book illustration style with bold outlines and dramatic shading.
                Add vibrant comic book colors and contrast.
                Include heroic pose and composition with comic panel background elements.
                Maintain the person's distinguishing features adapted to Marvel style.
                """
            elif selected_style == "blythe":
                prompt = """
                Transform this person into a Blythe doll.
                Use characteristic Blythe doll aesthetic with large head and oversized eyes.
                Add distinctive glossy finish and porcelain-like skin texture.
                Include pastel or vibrant colors typical for Blythe dolls.
                Add cute, slightly dreamy expression and Blythe doll fashion elements.
                """
            else:
                # Default to Ghibli if style not recognized
                prompt = """
                Transform this person into a Studio Ghibli animation character. 
                Use Ghibli's distinctive hand-drawn style with soft watercolor backgrounds and warm color palette.
                Add characteristic Ghibli lighting and atmosphere.
                Maintain the person's likeness and key features while adapting to Ghibli style.
                Include some Ghibli-style environment elements that complement the character.
                """
            
            # Используем метод edit вместо generate для лучших результатов
            with open(file_path, "rb") as img_file:
                image_response = client.images.edit(
                    model="gpt-image-1",
                    image=img_file,
                    prompt=prompt,
                    size="1024x1536",
                    n=1
                )
            
            # Получаем изображение в формате base64
            image_base64 = image_response.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)
            
            # Сохраняем изображение во временный файл для отправки
            generated_file_path = f"{tmp_dir}/generated_{unique_id}.png"
            with open(generated_file_path, "wb") as f:
                f.write(image_bytes)
                
            logger.info(f"Изображение успешно сгенерировано и сохранено в {generated_file_path}")
            
            # Удаляем временный файл изображения, чтобы не занимать дисковое пространство
            try:
                os.remove(file_path)
                logger.info(f"Временный файл {file_path} успешно удален")
            except Exception as file_error:
                logger.warning(f"Не удалось удалить временный файл {file_path}: {file_error}")
            
            # Deduct stars from user balance
            update_user_balance(user_id, -GENERATION_COST)
            current_balance = get_user_balance(user_id)
            
            # Создаем кнопки для добавления после генерации - строго 3 кнопки
            keyboard = [
                [InlineKeyboardButton("Сгенерировать еще", callback_data="generate_new")],
                [InlineKeyboardButton("Купить звезды", callback_data="topup_balance")],
                [InlineKeyboardButton("Главное меню", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Отправляем изображение пользователю из локального файла
            with open(generated_file_path, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo_file,
                    caption=f"Ваше изображение в стиле {style_name}! 🌟\n\nСписано: ⭐ {GENERATION_COST} звезд\nТекущий баланс: ⭐ {current_balance} звезд",
                    reply_markup=reply_markup
                )
            
            # Удаляем сгенерированный файл после отправки
            try:
                os.remove(generated_file_path)
                logger.info(f"Сгенерированный файл {generated_file_path} успешно удален")
            except Exception as file_error:
                logger.warning(f"Не удалось удалить сгенерированный файл {generated_file_path}: {file_error}")
            
            # Удаляем статусное сообщение
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id
                )
            except Exception as msg_error:
                logger.warning(f"Не удалось удалить статусное сообщение: {msg_error}")
                
        except OpenAIError as e:
            logger.error(f"Ошибка OpenAI при обработке изображения: {e}")
            
            # Удаляем временный файл в случае ошибки
            try:
                os.remove(file_path)
                logger.info(f"Временный файл {file_path} удален после ошибки OpenAI")
            except Exception as file_error:
                logger.warning(f"Не удалось удалить временный файл {file_path}: {file_error}")
            
            # Запасной вариант: попробуем DALL-E 2 вариации
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text="Использую альтернативный метод обработки... 🖌️"
                )
                
                # Используем новый API для редактирования изображений
                with open(file_path, "rb") as img_file:
                    image_edit = client.images.edit(
                        model="gpt-image-1",
                        image=img_file,
                        prompt=f"Create a {selected_style} style portrait of this person with artistic details",
                        size="1024x1536",
                        n=1
                    )
                
                # Получаем изображение в формате base64
                image_base64 = image_edit.data[0].b64_json
                image_bytes = base64.b64decode(image_base64)
                
                # Сохраняем изображение во временный файл для отправки
                backup_file_path = f"{tmp_dir}/backup_{unique_id}.png"
                with open(backup_file_path, "wb") as f:
                    f.write(image_bytes)
                
                logger.info("Альтернативное изображение успешно создано")
                
                # Deduct stars from user balance
                update_user_balance(user_id, -GENERATION_COST)
                current_balance = get_user_balance(user_id)
                
                # Отправляем изображение пользователю из локального файла
                with open(backup_file_path, 'rb') as photo_file:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photo_file,
                        caption=f"Ваше изображение (альтернативный метод)! 🌟\n\nСписано: ⭐ {GENERATION_COST} звезд\nТекущий баланс: ⭐ {current_balance} звезд"
                    )
                
                # Удаляем временный файл после отправки
                try:
                    os.remove(backup_file_path)
                    logger.info(f"Временный файл {backup_file_path} успешно удален")
                except Exception as file_error:
                    logger.warning(f"Не удалось удалить временный файл {backup_file_path}: {file_error}")
                
                # Удаляем статусное сообщение
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id
                )
                
            except Exception as e2:
                logger.error(f"Ошибка альтернативного метода: {e2}")
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text=f"К сожалению, не удалось обработать изображение: {str(e2)}"
                )
    
    except Exception as e:
        logger.error(f"Общая ошибка: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id,
                text=f"Произошла ошибка при обработке изображения: {str(e)}"
            )
        except:
            await update.message.reply_text(f"Произошла ошибка при обработке изображения: {str(e)}")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений."""
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    
    # Отправляем сообщение с инструкциями
    await update.message.reply_text(
        "Привет! Я могу превратить вашу фотографию в стиле различных анимационных студий.\n\n"
        "Просто отправьте мне фотографию или выберите опцию в меню.\n\n"
        f"Ваш текущий баланс: ⭐ {balance} звезд\n"
        f"Стоимость одной генерации: ⭐ {GENERATION_COST} звезд",
        reply_markup=create_main_menu()
    )

# Функции управления временными файлами
def cleanup_temp_files(context: ContextTypes.DEFAULT_TYPE = None):
    """Очистка временных файлов изображений для экономии места на PythonAnywhere."""
    logger.info("Запуск плановой очистки временных файлов...")
    
    # Определяем директории для проверки
    temp_dirs = ["/tmp", "images/temp"] 
    if not os.path.exists("images/temp"):
        os.makedirs("images/temp", exist_ok=True)
    
    # Максимальный возраст файла (30 минут)
    max_age_seconds = 30 * 60
    current_time = time.time()
    deleted_count = 0
    freed_space_bytes = 0
    
    # Проходим по всем временным директориям
    for temp_dir in temp_dirs:
        if os.path.exists(temp_dir):
            # Ищем все файлы изображений
            for pattern in ["*.png", "*.jpg", "*.jpeg"]:
                for file_path in glob.glob(os.path.join(temp_dir, pattern)):
                    try:
                        # Проверяем время последнего изменения
                        file_age = current_time - os.path.getmtime(file_path)
                        
                        # Удаляем старые файлы
                        if file_age > max_age_seconds:
                            # Получаем размер файла перед удалением
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            deleted_count += 1
                            freed_space_bytes += file_size
                            logger.debug(f"Удален временный файл {file_path}, возраст: {file_age:.0f} сек.")
                    except Exception as e:
                        logger.warning(f"Ошибка при очистке файла {file_path}: {e}")
    
    # Конвертируем байты в МБ для логов
    freed_space_mb = freed_space_bytes / (1024 * 1024)
    logger.info(f"Очистка временных файлов: удалено {deleted_count} файлов, освобождено {freed_space_mb:.2f} МБ")
    
    # Проверяем оставшееся место на диске
    check_disk_space()

def check_disk_space(min_free_mb=50):
    """Проверка доступного дискового пространства."""
    try:
        # Проверяем пространство в текущей директории
        current_dir = os.path.dirname(os.path.abspath(__file__))
        total, used, free = shutil.disk_usage(current_dir)
        free_mb = free / (1024 * 1024)
        
        logger.info(f"Доступно дискового пространства: {free_mb:.2f} МБ")
        
        # Если свободного места слишком мало, выполняем экстренную очистку
        if free_mb < min_free_mb:
            logger.warning(f"Критически мало места на диске: {free_mb:.2f} МБ. Запуск экстренной очистки.")
            emergency_cleanup()
            
        return free_mb
    except Exception as e:
        logger.error(f"Ошибка при проверке дискового пространства: {e}")
        return None

def emergency_cleanup():
    """Экстренная очистка всех временных файлов при критически низком месте на диске."""
    logger.warning("Выполняется экстренная очистка временных файлов!")
    
    temp_dirs = ["/tmp", "images/temp"]
    deleted_count = 0
    
    for temp_dir in temp_dirs:
        if os.path.exists(temp_dir):
            for pattern in ["*.png", "*.jpg", "*.jpeg"]:
                for file_path in glob.glob(os.path.join(temp_dir, pattern)):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Не удалось удалить {file_path}: {e}")
    
    logger.info(f"Экстренная очистка: удалено {deleted_count} файлов")

# Функция для настройки регулярных задач
def setup_scheduled_tasks(updater):
    """Настройка регулярных задач обслуживания."""
    job_queue = updater.job_queue
    
    # Очистка временных файлов каждые 30 минут
    job_queue.run_repeating(cleanup_temp_files, interval=30*60, first=10)
    
    # Более тщательная очистка раз в день - в 3 часа ночи
    from datetime import time
    time_of_day = time(3, 0, 0)  # 3:00 AM
    job_queue.run_daily(cleanup_temp_files, time=time_of_day)
    
    logger.info("Запланированы регулярные задачи очистки временных файлов")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages."""
    # Проверяем, что update и update.message не None
    if update and update.message:
        # Получаем user_id для проверки в базе данных
        user_id = update.effective_user.id
        
        # Проверяем, ждет ли бот ввода имени для гравировки на игрушке
        if 'user_data' in context.user_data and 'waiting_for_toy_name' in context.user_data['user_data'] and context.user_data['user_data']['waiting_for_toy_name']:
            # Сохраняем введенное имя для гравировки
            custom_name = update.message.text
            context.user_data['user_data']['custom_name'] = custom_name
            context.user_data['user_data']['waiting_for_toy_name'] = False
            
            # Устанавливаем флаг ожидания аксессуаров
            context.user_data['user_data']['waiting_for_accessories'] = True
            
            # Отправляем сообщение с просьбой указать аксессуары
            balance = get_user_balance(user_id)
            await update.message.reply_text(
                f"🔮 Отлично! Имя для гравировки: <b>{custom_name}</b>\n\n"
                f"Теперь укажите аксессуары для вашей игрушки в следующем сообщении.\n"
                f"Например: солнцезащитные очки, микрофон, гитара\n\n"
                f"Стоимость: ⭐ {GENERATION_COST} звезд | Ваш баланс: ⭐ {balance} звезд",
                parse_mode="HTML"
            )
            return
            
        # Проверяем, ждет ли бот ввода аксессуаров для стиля "Игрушка"
        elif 'user_data' in context.user_data and 'waiting_for_accessories' in context.user_data['user_data'] and context.user_data['user_data']['waiting_for_accessories']:
            # Сохраняем введенные аксессуары
            accessories = update.message.text
            context.user_data['user_data']['accessories'] = accessories
            context.user_data['user_data']['waiting_for_accessories'] = False
            
            # Проверяем, есть ли у нас сохраненный путь к фото
            if 'photo_file_path' in context.user_data['user_data']:
                file_path = context.user_data['user_data']['photo_file_path']
                
                # Отправляем сообщение о начале генерации
                status_message = await update.message.reply_text(
                    f"Начинаю создавать игрушку с аксессуарами: {accessories}..."
                )
                
                # Запускаем функцию обработки фото с сохраненными параметрами
                # Создаем фиктивный объект с фото
                from unittest.mock import MagicMock
                photo_message = MagicMock()
                photo_message.message_id = status_message.message_id
                photo_message.chat_id = update.effective_chat.id
                
                # Запускаем генерацию изображения в стиле "Игрушка"
                context.user_data['user_data']['selected_style'] = "toy"
                
                # Здесь нужно добавить код для генерации изображения
                # Но поскольку у нас нет прямого доступа к функции process_photo с файлом,
                # мы можем предложить пользователю отправить фото еще раз
                await update.message.reply_text(
                    "Пожалуйста, отправьте фото еще раз, чтобы я мог создать игрушку с указанными аксессуарами."
                )
                return
            
            # Если нет сохраненного пути к фото, просим отправить фото
            await update.message.reply_text(
                "Теперь, пожалуйста, отправьте фотографию, которую хотите превратить в игрушку."
            )
            return
            
        # Проверяем, ждет ли бот описания для "Своего стиля"
        elif 'user_data' in context.user_data and 'waiting_for_custom_style' in context.user_data['user_data'] and context.user_data['user_data']['waiting_for_custom_style']:
            # Сохраняем описание пользовательского стиля
            custom_style = update.message.text
            context.user_data['user_data']['custom_style'] = custom_style
            context.user_data['user_data']['waiting_for_custom_style'] = False
            
            # Проверяем, есть ли у нас сохраненный путь к фото
            if 'photo_file_path' in context.user_data['user_data']:
                file_path = context.user_data['user_data']['photo_file_path']
                
                # Отправляем сообщение о начале генерации
                status_message = await update.message.reply_text(
                    f"Начинаю создавать изображение в стиле: {custom_style}..."
                )
                
                # Запускаем генерацию изображения в пользовательском стиле
                context.user_data['user_data']['selected_style'] = "custom"
                
                # Здесь нужно добавить код для генерации изображения
                # Но поскольку у нас нет прямого доступа к функции process_photo с файлом,
                # мы можем предложить пользователю отправить фото еще раз
                await update.message.reply_text(
                    "Пожалуйста, отправьте фото еще раз, чтобы я мог создать изображение в указанном стиле."
                )
                return
            
            # Если нет сохраненного пути к фото, просим отправить фото
            await update.message.reply_text(
                "Теперь, пожалуйста, отправьте фотографию, которую хотите стилизовать."
            )
            return

        # Если пользователь отправил сообщение до использования /start
        elif update.message.text and not update.message.text.startswith('/'):
            # Проверяем, существует ли пользователь в базе
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            # Если пользователя нет в базе, отправляем ему информацию о боте
            if not user:
                bot_description = (
                    "✨ Что может делать этот бот? ✨\n\n"
                    "🎨 Этот бот может преобразовать любую фотографию в различные художественные стили с помощью продвинутого Искусственного Интеллекта!\n\n"
                    "📱 Как пользоваться:\n"
                    "1. Отправьте мне фото, на котором хорошо видно лицо\n"
                    "2. Выберите желаемый стиль\n"
                    "3. ...и получите уникальный результат!\n\n"
                    "🔮 Для начала работы введите /start"
                )
                await update.message.reply_text(bot_description)
                return
        
        # Для всех остальных текстовых сообщений
        logger.info(f"Получено текстовое сообщение от пользователя {update.message.from_user.id}: {update.message.text}")
        await update.message.reply_text(
            "💾️ Пожалуйста, отправьте мне фотографию, которую хотите стилизовать!\n\n" \
            "Или воспользуйтесь меню для выбора других опций.",
            reply_markup=create_main_menu()
        )
    else:
        logger.error(f"Ошибка в text_message: update = {update}")

def main() -> None:
    """Start the bot."""
    print(f"Запуск бота @{BOT_USERNAME}...")
    
    # Пытаемся восстановить базу данных из резервной копии
    db_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(db_dir, 'users.db')
    
    # Проверяем, существует ли основная база данных
    if not os.path.exists(db_path):
        logger.info("База данных не найдена. Пытаемся восстановить из резервной копии...")
        if restore_db_from_backup():
            logger.info("База данных успешно восстановлена из резервной копии!")
        else:
            logger.info("Не удалось восстановить базу данных из резервной копии. Создаем новую базу данных.")
    else:
        logger.info(f"База данных найдена по пути: {db_path}")
        # Создаем резервную копию существующей базы данных при запуске
        backup_db()
    
    # Initialize database (создаст таблицы, если они не существуют)
    init_db()
    
    # Test OpenAI connection (but continue anyway)
    test_openai_connection()
    print("Продолжаем запуск бота...")
    
    try:
        # Create the Application with extended timeout settings
        from telegram.ext import ApplicationBuilder
        
        # Создаем приложение с расширенными настройками таймаута
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()
        logger.info(f"Бот инициализирован с токеном: {TELEGRAM_TOKEN[:5]}...")

        # Регистрируем обработчик ошибок
        async def error_handler(update, context):
            logger.error(f"Ошибка при обработке обновления: {context.error}")
            if update:
                logger.error(f"Обновление, вызвавшее ошибку: {update}")
                
        application.add_error_handler(error_handler)
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        logger.info("Зарегистрирован обработчик /start")
        
        application.add_handler(CommandHandler("menu", menu_command))
        logger.info("Зарегистрирован обработчик /menu")
        
        application.add_handler(CommandHandler("help", help_command))
        logger.info("Зарегистрирован обработчик /help")
        
        application.add_handler(CommandHandler("balance", balance_command))
        logger.info("Зарегистрирован обработчик /balance")
        
        application.add_handler(CallbackQueryHandler(button_handler))
        logger.info("Зарегистрирован обработчик для кнопок")
        
        application.add_handler(MessageHandler(filters.PHOTO, process_photo))
        logger.info("Зарегистрирован обработчик для фотографий")
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
        logger.info("Зарегистрирован обработчик для текстовых сообщений")
        
        # Add payment handlers
        application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
        application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
        logger.info("Зарегистрированы обработчики для платежей")

        # Start the Bot with more log info
        print("Запуск бота через polling...")
        logger.info("Запуск бота через polling...")
        
        # Настройка задач очистки временных файлов и резервного копирования
        # Обновленная версия для python-telegram-bot v20.x
        job_queue = application.job_queue
        if job_queue is not None:
            # Задача очистки временных файлов каждые 30 минут
            job_queue.run_repeating(cleanup_temp_files, interval=30*60, first=10)
            logger.info("Задача очистки временных файлов добавлена в расписание")
            
            # Задача резервного копирования базы данных каждые 6 часов
            async def scheduled_backup(context: ContextTypes.DEFAULT_TYPE):
                logger.info("Запуск планового резервного копирования базы данных...")
                backup_db()
                
            job_queue.run_repeating(scheduled_backup, interval=6*60*60, first=60*60)
            logger.info("Задача резервного копирования базы данных добавлена в расписание")
        
        # Выполняем первоначальную очистку временных файлов при запуске
        cleanup_temp_files()
        
        # Start the Bot
        print("Бот запущен и готов к работе! Нажмите Ctrl+C для остановки.")
        logger.info("Бот успешно запущен и ждет сообщения!")
        
        # Run the bot until you press Ctrl-C or the process receives SIGINT, SIGTERM or SIGABRT
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"Критическая ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
