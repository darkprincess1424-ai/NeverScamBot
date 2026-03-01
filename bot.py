import logging
import sqlite3
import datetime
import re
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = 'YOUR_BOT_TOKEN_HERE'  # Замените на ваш токен
MAIN_ADMIN_ID = 8281804228
BOT_USERNAME = 'NeverScamsBot'

# ID фотографий
PHOTO_SCAMMER = 'AgACAgIAAxkBAAMVaaHg7_zNX5m5N06DXq54t-ZKRKEAAsMRaxuOLhBJCDq_AAGQ1rI8AQADAgADeQADOgQ'  # Вор
PHOTO_GUARANT = 'AgACAgIAAxkBAAMPaaHgzLypR6GVRk4yINYxDbcqKO0AAsERaxuOLhBJLlG-AytNhLQBAAMCAAN5AAM6BA'  # Гарант
PHOTO_USER = 'AgACAgIAAxkBAAMdaaHhHw8ddb-2cgABuClV9dHSz4XQAALIEWsbji4QSXh9Mm3i5WDHAQADAgADeQADOgQ'    # Обычный пользователь
PHOTO_ADMIN = 'AgACAgIAAxkBAAMZaaHhBY3SKHCFn7qlk4MNpmWAigIAAscRaxuOLhBJN9n-Jy8AAdwyAQADAgADeQADOgQ'  # Админ

# Создаем Flask приложение
app = Flask(__name__)

# Инициализация бота
bot_app = Application.builder().token(TOKEN).build()

# База данных
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  role TEXT DEFAULT 'user',
                  warns INTEGER DEFAULT 0,
                  mute_until TEXT,
                  added_scammers INTEGER DEFAULT 0,
                  search_count INTEGER DEFAULT 0)''')
    
    # Таблица воров
    c.execute('''CREATE TABLE IF NOT EXISTS scammers
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  reason TEXT,
                  proofs TEXT,
                  added_by INTEGER,
                  added_date TEXT)''')
    
    # Таблица гарантов
    c.execute('''CREATE TABLE IF NOT EXISTS guarants
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  info_link TEXT,
                  proofs_link TEXT,
                  added_by INTEGER,
                  added_date TEXT)''')
    
    # Таблица для учета поисков
    c.execute('''CREATE TABLE IF NOT EXISTS searches
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  searched_user_id INTEGER,
                  search_date TEXT)''')
    
    # Таблица для групп
    c.execute('''CREATE TABLE IF NOT EXISTS groups
                 (chat_id INTEGER PRIMARY KEY,
                  is_open BOOLEAN DEFAULT 1)''')
    
    conn.commit()
    conn.close()
    
    # Добавляем главного админа
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, role) VALUES (?, 'admin')", (MAIN_ADMIN_ID,))
    conn.commit()
    conn.close()

# Пересоздаем базу данных
import os
if os.path.exists('bot_database.db'):
    os.remove('bot_database.db')
    print("🗑️ Старая база данных удалена")

init_db()

# Функции для работы с БД
def get_user_role(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'user'

def get_user_by_username(username):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT user_id, role FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result

def update_user_role(user_id, role, username=None):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    if username:
        c.execute("INSERT OR REPLACE INTO users (user_id, username, role) VALUES (?, ?, ?)", 
                  (user_id, username, role))
    else:
        c.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    
    conn.commit()
    conn.close()

def update_user_id(old_id, new_id, username):
    """Обновляет ID пользователя во всех таблицах"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    print(f"🔄 Обновление ID для {username}: {old_id} -> {new_id}")
    
    # Проверяем, есть ли пользователь в таблице воров
    c.execute("SELECT * FROM scammers WHERE user_id = ?", (old_id,))
    scammer_data = c.fetchone()
    
    if scammer_data:
        # Если есть в ворах, переносим данные
        c.execute("INSERT OR REPLACE INTO scammers (user_id, username, reason, proofs, added_by, added_date) VALUES (?, ?, ?, ?, ?, ?)",
                  (new_id, scammer_data[1], scammer_data[2], scammer_data[3], scammer_data[4], scammer_data[5]))
        c.execute("DELETE FROM scammers WHERE user_id = ?", (old_id,))
        print(f"✅ Данные вора перенесены на новый ID")
    
    # Проверяем, есть ли пользователь в таблице гарантов
    c.execute("SELECT * FROM guarants WHERE user_id = ?", (old_id,))
    guarant_data = c.fetchone()
    
    if guarant_data:
        # Если есть в гарантах, переносим данные
        c.execute("INSERT OR REPLACE INTO guarants (user_id, username, info_link, proofs_link, added_by, added_date) VALUES (?, ?, ?, ?, ?, ?)",
                  (new_id, guarant_data[1], guarant_data[2], guarant_data[3], guarant_data[4], guarant_data[5]))
        c.execute("DELETE FROM guarants WHERE user_id = ?", (old_id,))
        print(f"✅ Данные гаранта перенесены на новый ID")
    
    # Обновляем роль в таблице users
    c.execute("SELECT role, warns, mute_until, added_scammers, search_count FROM users WHERE user_id = ?", (old_id,))
    user_data = c.fetchone()
    
    if user_data:
        role, warns, mute_until, added_scammers, search_count = user_data
        c.execute("INSERT OR REPLACE INTO users (user_id, username, role, warns, mute_until, added_scammers, search_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (new_id, username, role, warns, mute_until, added_scammers, search_count))
        c.execute("DELETE FROM users WHERE user_id = ?", (old_id,))
        print(f"✅ Данные пользователя перенесены на новый ID")
    else:
        # Если пользователя не было, создаем нового
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                  (new_id, username))
    
    conn.commit()
    conn.close()
    print(f"✅ ID пользователя {username} успешно обновлен")

def increment_search_count(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET search_count = search_count + 1 WHERE user_id = ?", (user_id,))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, search_count) VALUES (?, 1)", (user_id,))
    conn.commit()
    conn.close()

def get_search_count(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT search_count FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def add_scammer(user_id, username, reason, proofs, added_by):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    added_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Проверяем, есть ли уже пользователь с таким username
    c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    existing_user = c.fetchone()
    
    if existing_user and existing_user[0] != user_id:
        # Если пользователь уже есть с другим ID, используем существующий ID
        user_id = existing_user[0]
        print(f"⚠️ Пользователь {username} уже существует с ID {user_id}, используем его")
    
    c.execute("INSERT OR REPLACE INTO scammers (user_id, username, reason, proofs, added_by, added_date) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, reason, proofs, added_by, added_date))
    c.execute("UPDATE users SET role = 'scammer', username = ? WHERE user_id = ?", (username, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, username, role) VALUES (?, ?, 'scammer')", (user_id, username))
    c.execute("UPDATE users SET added_scammers = added_scammers + 1 WHERE user_id = ?", (added_by,))
    conn.commit()
    conn.close()
    print(f"✅ Вор {username} (ID: {user_id}) добавлен в базу")

def remove_scammer(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("DELETE FROM scammers WHERE user_id = ?", (user_id,))
    c.execute("UPDATE users SET role = 'user' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    print(f"✅ Вор с ID {user_id} удален из базы")

def add_guarant(user_id, username, info_link, proofs_link, added_by):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    added_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Проверяем, есть ли уже пользователь с таким username
    c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    existing_user = c.fetchone()
    
    if existing_user and existing_user[0] != user_id:
        # Если пользователь уже есть с другим ID, используем существующий ID
        user_id = existing_user[0]
        print(f"⚠️ Пользователь {username} уже существует с ID {user_id}, используем его")
    
    c.execute("INSERT OR REPLACE INTO guarants (user_id, username, info_link, proofs_link, added_by, added_date) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, info_link, proofs_link, added_by, added_date))
    c.execute("UPDATE users SET role = 'guarant', username = ? WHERE user_id = ?", (username, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, username, role) VALUES (?, ?, 'guarant')", (user_id, username))
    conn.commit()
    conn.close()

def remove_guarant(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("DELETE FROM guarants WHERE user_id = ?", (user_id,))
    c.execute("UPDATE users SET role = 'user' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_scammer_info(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM scammers WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_scammer_by_username(username):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM scammers WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result

def get_guarant_info(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM guarants WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_guarant_by_username(username):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM guarants WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result

def get_all_guarants():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, info_link, proofs_link FROM guarants")
    result = c.fetchall()
    conn.close()
    return result

def get_user_added_count(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT added_scammers FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def set_group_status(chat_id, is_open):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO groups (chat_id, is_open) VALUES (?, ?)", (chat_id, is_open))
    conn.commit()
    conn.close()

def get_group_status(chat_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT is_open FROM groups WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 1

def add_warn(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET warns = warns + 1 WHERE user_id = ?", (user_id,))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, warns) VALUES (?, 1)", (user_id,))
    conn.commit()
    c.execute("SELECT warns FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 1

def set_mute(user_id, until):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET mute_until = ? WHERE user_id = ?", (until, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, mute_until) VALUES (?, ?)", (user_id, until))
    conn.commit()
    conn.close()

def is_muted(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT mute_until FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result and result[0]:
        mute_until = datetime.datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        return mute_until > datetime.datetime.now()
    return False

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    print(f"🚀 Пользователь {user.username} (ID: {user.id}) запустил бота")
    
    # Проверяем, есть ли пользователь в базе с таким username
    user_info = get_user_by_username(user.username)
    
    if user_info and user_info[0] != user.id:
        # Если нашли пользователя с таким username но другим ID, обновляем ID
        print(f"🔄 Обнаружено несоответствие ID: старый {user_info[0]}, новый {user.id}")
        update_user_id(user_info[0], user.id, user.username)
    else:
        # Сохраняем информацию о пользователе
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                  (user.id, user.username))
        conn.commit()
        conn.close()
        print(f"✅ Пользователь {user.username} сохранен в базе")
    
    # Клавиатура около клавиатуры
    keyboard = [
        [KeyboardButton("👤 Мой профиль")],
        [KeyboardButton("📋 Список гарантов")],
        [KeyboardButton("📚 Команды бота")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Текст приветствия
    welcome_text = """👋Привет, Путешественник!

⭐️• Этот бот поможет проверить на добросовестность продавцов в сфере услуг(и не только) по игре ”Genshin Impact”.

⭐️• В дальнейшем у нас появится своя база данных, в которой будут находиться только честные продавцы, которым вы можете доверять!

📍• В нашей предложке. Вы можете наказать похитителя ваших сокровищ 💎

🔮• Так же у нас есть новостной канал, в котором часто проходят наборы в администрацию или же гарантов."""

    # Инлайн кнопки - ТОЛЬКО НОВОСТНОЙ КАНАЛ
    inline_keyboard = [
        [InlineKeyboardButton("📢 Новостной канал", url="https://t.me/NeverScamLaboratory")]
    ]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    # Отправляем текст с кнопками
    await update.message.reply_text(
        text=welcome_text,
        reply_markup=inline_markup
    )
    
    # Отправляем клавиатуру отдельным сообщением, если это личка
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=reply_markup
        )

# Обработка текстовых сообщений (кнопки)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    if text == "👤 Мой профиль":
        await check_profile(update, context, user.id, user.username)
    elif text == "📋 Список гарантов":
        await list_guarants(update, context)
    elif text == "📚 Команды бота":
        await show_commands(update, context)

# Проверка профиля
async def check_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None, username=None):
    # Если передан user_id, используем его, иначе берем из update
    if user_id is None:
        user = update.effective_user
        user_id = user.id
        username = user.username
    
    print(f"🔍 Проверка профиля: {username} (ID: {user_id})")
    
    # Проверяем, есть ли пользователь в базе с таким username но другим ID
    user_info = get_user_by_username(username)
    if user_info and user_info[0] != user_id:
        print(f"🔄 Обновляем ID перед проверкой: {user_info[0]} -> {user_id}")
        update_user_id(user_info[0], user_id, username)
    
    # Увеличиваем счетчик поиска для проверяемого
    increment_search_count(user_id)
    
    # Получаем информацию о пользователе
    role = get_user_role(user_id)
    search_count = get_search_count(user_id)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"📊 Роль в базе: {role}")
    
    # Проверяем, есть ли пользователь в таблице воров
    scammer_info = get_scammer_info(user_id)
    if scammer_info:
        print(f"⚠️ Найден в таблице воров")
        role = 'scammer'
    
    # Проверяем, есть ли пользователь в таблице гарантов
    guarant_info = get_guarant_info(user_id)
    if guarant_info:
        print(f"✅ Найден в таблице гарантов")
        role = 'guarant'
    
    # Создаем инлайн кнопки
    inline_keyboard = [
        [InlineKeyboardButton("👮‍♂️ Наказать вора", url="https://t.me/neverscamsbase")]
    ]
    
    # Добавляем кнопку с ссылкой только если пользователь существует в Telegram
    if user_id < 1000000000:  # Реальные ID в Telegram обычно меньше 10^9
        inline_keyboard.append([InlineKeyboardButton("🔗 Вечная ссылка", url=f"tg://user?id={user_id}")])
    
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    # Формируем имя пользователя для отображения
    display_name = username if username else f"ID {user_id}"
    
    if role == 'scammer':
        if scammer_info:
            reason = scammer_info[2] if len(scammer_info) > 2 and scammer_info[2] else "Не указана"
            proofs = scammer_info[3] if len(scammer_info) > 3 and scammer_info[3] else "Нет ссылок"
        else:
            reason = "Мошенничество"
            proofs = "Нет ссылок"
        
        text = f"""🕵️‍♂️ Цель: @{display_name}
🔍 Статус проверки...
❗️ Вердикт: ⚠️ ВОР

📜 Причина: {reason}
📎 Доказательства: {proofs}

⚠️ Цель имеет плохую репутацию 
🚫 Совет: Заблокировать!

🔍 Цель искали: {search_count} раз(а)

🔝 Проверил @{BOT_USERNAME}
🗓 {current_time}

❤️ от Синьоры: Заблокируйте похитителя!"""
        
        await update.message.reply_photo(
            photo=PHOTO_SCAMMER,
            caption=text,
            reply_markup=inline_markup
        )
        
    elif role == 'guarant':
        if guarant_info:
            info_link = guarant_info[3] if len(guarant_info) > 3 and guarant_info[3] else "Нет ссылки"
            proofs_link = guarant_info[4] if len(guarant_info) > 4 and guarant_info[4] else "Нет ссылки"
        else:
            info_link = "Нет ссылки"
            proofs_link = "Нет ссылки"
        
        text = f"""🕵️‍♂️ Цель: @{display_name}
🔍 Статус проверки...
✅ Вердикт: 💯 ГАРАНТ

📌 Инфо: {info_link}
📋 Досье: {proofs_link}

🔍 Цель искали: {search_count} раз(а)

🔝 Проверил @{BOT_USERNAME}
🗓 {current_time}

❤️ от Синьоры: Успешной сделки!"""
        
        await update.message.reply_photo(
            photo=PHOTO_GUARANT,
            caption=text,
            reply_markup=inline_markup
        )
        
    elif role == 'admin':
        added_count = get_user_added_count(user_id)
        
        text = f"""🕵️‍♂️ Цель @{display_name}
🔍 Статус проверки...
👑 Вердикт: АДМИНИСТРАТОР

📊 Добавлено воров: {added_count}

🔍 Цель искали: {search_count} раз(а)

🔝 Проверил @{BOT_USERNAME}
🗓 {current_time}

❤️ от Синьоры: Успешной сделки!"""
        
        await update.message.reply_photo(
            photo=PHOTO_ADMIN,
            caption=text,
            reply_markup=inline_markup
        )
        
    else:  # обычный пользователь
        text = f"""🕵️‍♂️ Цель: @{display_name}
🔍 Статус проверки...
✅ Вердикт: ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ

🔍 Цель искали: {search_count} раз(а)

🔝 Проверил @{BOT_USERNAME}
🗓 {current_time}

❤️ от Синьоры: Успешной сделки!"""
        
        await update.message.reply_photo(
            photo=PHOTO_USER,
            caption=text,
            reply_markup=inline_markup
        )

# Список гарантов
async def list_guarants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guarants = get_all_guarants()
    
    if not guarants:
        await update.message.reply_text("📭 Список гарантов пуст.")
        return
    
    text = "📋 СПИСОК ГАРАНТОВ:\n\n"
    for guarant in guarants:
        user_id, username, info_link, proofs_link = guarant
        display_name = username if username else f"ID {user_id}"
        text += f"👤 @{display_name}\n"
        text += f"📌 Инфо: {info_link}\n"
        text += f"📋 Пруфы: {proofs_link}\n\n"
    
    if len(text) > 4096:
        for x in range(0, len(text), 4096):
            await update.message.reply_text(text[x:x+4096])
    else:
        await update.message.reply_text(text)

# Команды бота
async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    commands_text = """📚 ОСНОВНЫЕ КОМАНДЫ:

🔍 /check @username - проверить пользователя
🔍 /check (ответ на сообщение) - проверить пользователя
🔍 /check me - проверить себя
📋 /guarants - список гарантов
📸 /get_photo_id - получить ID фото (ответом на фото)
📊 /stats - статистика бота"""
    
    if role == 'admin' or user_id == MAIN_ADMIN_ID:
        commands_text += """

👑 АДМИН КОМАНДЫ:
➕ /add_garant @username ссылка_инфо ссылка_пруфы - добавить гаранта
➖ /del_garant @username - удалить гаранта
👑 /add_admin @username - добавить администратора
⚠️ /add_vor @username причина | ссылка - добавить вора
✅ /del_vor @username - удалить вора
📋 /list_vors - список всех воров"""
    
    if user_id == MAIN_ADMIN_ID:
        commands_text += """

👥 ЧАТ КОМАНДЫ:
🔓 /open - открыть чат
🔒 /close - закрыть чат
⚠️ /warn @username - выдать предупреждение
🔇 /mute @username [минуты] - замутить пользователя"""
    
    await update.message.reply_text(commands_text)

# Команда /check
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    message = update.message
    
    # /check me
    if args and args[0].lower() == 'me':
        user = update.effective_user
        await check_profile(update, context, user.id, user.username)
        return
    
    # /check в ответ на сообщение
    if not args and message.reply_to_message:
        user_to_check = message.reply_to_message.from_user
        await check_profile(update, context, user_to_check.id, user_to_check.username)
        return
    
    # /check @username
    if args:
        username = args[0].replace('@', '')
        print(f"🔍 Проверка пользователя по команде: @{username}")
        
        # Сначала ищем в базе данных воров
        scammer_info = get_scammer_by_username(username)
        if scammer_info:
            user_id = scammer_info[0]
            print(f"⚠️ Найден вор в базе с ID {user_id}")
            await check_profile(update, context, user_id, username)
            return
        
        # Ищем в таблице гарантов
        guarant_info = get_guarant_by_username(username)
        if guarant_info:
            user_id = guarant_info[0]
            print(f"✅ Найден гарант в базе с ID {user_id}")
            await check_profile(update, context, user_id, username)
            return
        
        # Пытаемся получить информацию из Telegram
        try:
            print(f"🔍 Ищем пользователя @{username} в Telegram...")
            chat = await context.bot.get_chat(f"@{username}")
            user_id = chat.id
            print(f"✅ Найден в Telegram с ID {user_id}")
            
            # Проверяем, есть ли пользователь в базе с таким username
            user_info = get_user_by_username(username)
            if user_info and user_info[0] != user_id:
                print(f"🔄 Обновляем ID перед проверкой: {user_info[0]} -> {user_id}")
                update_user_id(user_info[0], user_id, username)
            else:
                # Сохраняем пользователя в базу
                conn = sqlite3.connect('bot_database.db')
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                          (user_id, username))
                conn.commit()
                conn.close()
            
            await check_profile(update, context, user_id, username)
            return
        except Exception as e:
            print(f"❌ Ошибка при поиске пользователя @{username} в Telegram: {e}")
            
            # Если не нашли в Telegram, создаем временного пользователя
            temp_user_id = abs(hash(username)) % (10**9) + 10**12
            
            # Проверяем, есть ли уже пользователь с таким username
            user_info = get_user_by_username(username)
            if user_info:
                # Если есть, используем существующий ID
                temp_user_id = user_info[0]
                print(f"⚠️ Используем существующий ID {temp_user_id} для {username}")
            else:
                # Сохраняем в базу как обычного пользователя
                conn = sqlite3.connect('bot_database.db')
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO users (user_id, username, role) VALUES (?, ?, 'user')",
                          (temp_user_id, username))
                conn.commit()
                conn.close()
                print(f"⚠️ Создан временный пользователь {username} с ID {temp_user_id}")
            
            await check_profile(update, context, temp_user_id, username)
            return
    
    await update.message.reply_text("❌ Использование: /check @username, /check (ответ на сообщение) или /check me")

# Команда /stats
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM scammers")
    total_scammers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM guarants")
    total_guarants = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM searches")
    total_searches = c.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""📊 СТАТИСТИКА БОТА:

👥 Всего пользователей: {total_users}
⚠️ Воров в базе: {total_scammers}
✅ Гарантов: {total_guarants}
🔍 Всего проверок: {total_searches}"""
    
    await update.message.reply_text(stats_text)

# Команда /list_vors
async def list_vors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    if role != 'admin' and user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT username, reason, proofs, added_date FROM scammers")
    vors = c.fetchall()
    conn.close()
    
    if not vors:
        await update.message.reply_text("📭 Список воров пуст.")
        return
    
    text = "⚠️ СПИСОК ВОРОВ:\n\n"
    for vor in vors:
        username, reason, proofs, added_date = vor
        display_name = username if username else "Неизвестно"
        text += f"👤 @{display_name}\n"
        text += f"📜 Причина: {reason}\n"
        text += f"📎 Доказательства: {proofs}\n"
        text += f"📅 Добавлен: {added_date}\n\n"
    
    if len(text) > 4096:
        for x in range(0, len(text), 4096):
            await update.message.reply_text(text[x:x+4096])
    else:
        await update.message.reply_text(text)

# Команда /guarants
async def guarants_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_guarants(update, context)

# Команда /add_garant
async def add_garant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin'] and user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Использование: /add_garant @username ссылка_инфо ссылка_пруфы")
        return
    
    username = args[0].replace('@', '')
    info_link = args[1]
    proofs_link = args[2]
    
    try:
        # Пытаемся получить информацию о пользователе из Telegram
        try:
            chat = await context.bot.get_chat(f"@{username}")
            target_user_id = chat.id
            add_guarant(target_user_id, username, info_link, proofs_link, user_id)
            await update.message.reply_text(f"✅ Гарант @{username} успешно добавлен!")
        except:
            # Если не нашли в Telegram, добавляем с временным ID
            temp_user_id = abs(hash(username)) % (10**9) + 10**12
            add_guarant(temp_user_id, username, info_link, proofs_link, user_id)
            await update.message.reply_text(
                f"⚠️ Пользователь @{username} не найден в Telegram, но добавлен в базу как гарант.\n"
                f"Когда он зайдет в бота, ID обновится автоматически."
            )
    except Exception as e:
        print(f"Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка при добавлении гаранта @{username}.")

# Команда /del_garant
async def del_garant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin'] and user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("❌ Использование: /del_garant @username")
        return
    
    username = args[0].replace('@', '')
    
    # Ищем в таблице гарантов по username
    guarant_info = get_guarant_by_username(username)
    
    if guarant_info:
        remove_guarant(guarant_info[0])
        await update.message.reply_text(f"✅ Гарант @{username} успешно удален!")
    else:
        await update.message.reply_text(f"❌ Гарант @{username} не найден в базе.")

# Команда /add_admin - ИСПРАВЛЕННАЯ
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может добавлять админов.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("❌ Использование: /add_admin @username")
        return
    
    username = args[0].replace('@', '')
    
    try:
        # Пытаемся получить информацию о пользователе из Telegram
        chat = await context.bot.get_chat(f"@{username}")
        target_user_id = chat.id
        update_user_role(target_user_id, 'admin', username)
        await update.message.reply_text(f"✅ Администратор @{username} успешно добавлен!")
    except Exception as e:
        print(f"Ошибка при поиске пользователя @{username}: {e}")
        
        # Если не нашли в Telegram, создаем временного пользователя
        temp_user_id = abs(hash(username)) % (10**9) + 10**12
        
        # Проверяем, есть ли уже пользователь с таким username в базе
        user_info = get_user_by_username(username)
        if user_info:
            # Если есть, используем существующий ID
            temp_user_id = user_info[0]
            update_user_role(temp_user_id, 'admin', username)
            await update.message.reply_text(f"✅ Администратор @{username} успешно добавлен (использован существующий ID)!")
        else:
            # Создаем нового пользователя с временным ID
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO users (user_id, username, role) VALUES (?, ?, 'admin')",
                      (temp_user_id, username))
            conn.commit()
            conn.close()
            await update.message.reply_text(
                f"⚠️ Пользователь @{username} не найден в Telegram, но добавлен в базу как администратор.\n"
                f"Когда он зайдет в бота, его ID обновится автоматически."
            )

# Команда /add_vor
async def add_vor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin'] and user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    # Объединяем аргументы и разделяем по |
    full_text = ' '.join(context.args)
    parts = full_text.split('|')
    
    if len(parts) < 2:
        await update.message.reply_text("❌ Использование: /add_vor @username причина | ссылка на пруфы")
        return
    
    username_part = parts[0].strip()
    reason = parts[1].strip()
    proofs = parts[2].strip() if len(parts) > 2 else "Нет ссылок"
    
    # Извлекаем username
    username_match = re.search(r'@(\w+)', username_part)
    if not username_match:
        await update.message.reply_text("❌ Укажите username в формате @username")
        return
    
    username = username_match.group(1)
    
    try:
        # Пытаемся получить информацию о пользователе из Telegram
        try:
            chat = await context.bot.get_chat(f"@{username}")
            target_user_id = chat.id
            await update.message.reply_text(f"✅ Пользователь @{username} найден в Telegram с ID {target_user_id}")
        except:
            # Если не нашли в Telegram, используем временный ID
            target_user_id = abs(hash(username)) % (10**9) + 10**12
            await update.message.reply_text(
                f"⚠️ Пользователь @{username} не найден в Telegram, будет добавлен с временным ID.\n"
                f"Когда он зайдет в бота, ID обновится автоматически."
            )
        
        add_scammer(target_user_id, username, reason, proofs, user_id)
        await update.message.reply_text(f"✅ Вор @{username} успешно добавлен в базу!")
        
    except Exception as e:
        print(f"Ошибка при добавлении вора: {e}")
        await update.message.reply_text(f"❌ Ошибка при добавлении вора @{username}.")

# Команда /del_vor
async def del_vor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    
    if role not in ['admin'] and user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("❌ Использование: /del_vor @username")
        return
    
    username = args[0].replace('@', '')
    
    # Ищем вора в базе по username
    scammer_info = get_scammer_by_username(username)
    if scammer_info:
        remove_scammer(scammer_info[0])
        await update.message.reply_text(f"✅ Вор @{username} успешно удален из базы!")
    else:
        await update.message.reply_text(f"❌ Вор @{username} не найден в базе.")

# Команды для групп
async def open_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может использовать эту команду.")
        return
    
    set_group_status(chat_id, True)
    await update.message.reply_text("🔓 Чат открыт. Все могут писать.")

async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может использовать эту команду.")
        return
    
    set_group_status(chat_id, False)
    await update.message.reply_text("🔒 Чат закрыт. Писать могут только администраторы.")

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может использовать эту команду.")
        return
    
    args = context.args
    if not args and not update.message.reply_to_message:
        await update.message.reply_text("❌ Использование: /warn @username или ответ на сообщение с /warn")
        return
    
    target_user = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    else:
        username = args[0].replace('@', '')
        try:
            chat = await context.bot.get_chat(f"@{username}")
            target_user = chat
        except:
            await update.message.reply_text(f"❌ Пользователь не найден.")
            return
    
    warns = add_warn(target_user.id)
    await update.message.reply_text(f"⚠️ Пользователю {target_user.mention_html()} выдано предупреждение. Всего предупреждений: {warns}", parse_mode=ParseMode.HTML)
    
    if warns >= 3:
        mute_until = datetime.datetime.now() + datetime.timedelta(hours=24)
        set_mute(target_user.id, mute_until.strftime("%Y-%m-%d %H:%M:%S"))
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions=ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🔇 Пользователь {target_user.mention_html()} получил мут на 24 часа (3/3 предупреждений)", parse_mode=ParseMode.HTML)

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может использовать эту команду.")
        return
    
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ Использование: /mute @username [время в минутах]")
        return
    
    username = args[0].replace('@', '')
    mute_minutes = int(args[1]) if len(args) > 1 else 60
    
    try:
        chat = await context.bot.get_chat(f"@{username}")
        target_user = chat
        
        mute_until = datetime.datetime.now() + datetime.timedelta(minutes=mute_minutes)
        set_mute(target_user.id, mute_until.strftime("%Y-%m-%d %H:%M:%S"))
        
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions=ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🔇 Пользователь {target_user.mention_html()} замучен на {mute_minutes} минут", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден.")

# Команда для получения ID фото
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("❌ Ответьте на фото этой командой, чтобы получить его ID.")
        return
    
    photo = update.message.reply_to_message.photo[-1]
    file_id = photo.file_id
    
    await update.message.reply_text(f"📸 ID фото: `{file_id}`", parse_mode=ParseMode.MARKDOWN)

# Фильтр сообщений в группах
async def group_message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    is_open = get_group_status(chat_id)
    
    if not is_open:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ['administrator', 'creator'] and user_id != MAIN_ADMIN_ID:
            await update.message.delete()
            return
    
    if is_muted(user_id):
        await update.message.delete()
        return

# Инициализация и запуск бота через Flask
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    asyncio.run_coroutine_threadsafe(bot_app.process_update(update), bot_app.loop)
    return 'OK', 200

@app.route('/')
def index():
    return 'Бот работает!', 200

def setup():
    """Настройка бота"""
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("check", check_command))
    bot_app.add_handler(CommandHandler("guarants", guarants_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(CommandHandler("list_vors", list_vors))
    bot_app.add_handler(CommandHandler("add_garant", add_garant))
    bot_app.add_handler(CommandHandler("del_garant", del_garant))
    bot_app.add_handler(CommandHandler("add_admin", add_admin))
    bot_app.add_handler(CommandHandler("add_vor", add_vor))
    bot_app.add_handler(CommandHandler("del_vor", del_vor))
    bot_app.add_handler(CommandHandler("open", open_chat))
    bot_app.add_handler(CommandHandler("close", close_chat))
    bot_app.add_handler(CommandHandler("warn", warn_user))
    bot_app.add_handler(CommandHandler("mute", mute_user))
    bot_app.add_handler(CommandHandler("get_photo_id", get_photo_id))
    
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, group_message_filter), group=1)

async def main():
    await bot_app.initialize()
    await bot_app.start()
    
    print("✅ Бот запущен и готов к работе!")
    print("=" * 50)
    print("📸 ID фотографий загружены")
    print("=" * 50)
    
    await bot_app.updater.start_polling()

if __name__ == '__main__':
    setup()
    
    print("🚀 Бот запускается в режиме polling...")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("❌ Бот остановлен")
    finally:
        loop.close()
