#!/data/data/com.termux/files/usr/bin/python3
import os
import sqlite3
import logging
import asyncio
import random
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# ========== ВАШИ ДАННЫЕ ==========
BOT_TOKEN = "8498581637:AAF4Z59SYbdP9Z2Jk6oM3EnJ0tsXAbQvPDw"
ADMIN_IDS = [6339108316]

# ========== КОНСТАНТЫ СТАТУСОВ ==========
STATUS_TYPES = {
    'basic': {
        'name': 'Базовый',
        'price_one_time': 50,
        'price_monthly': 10,
        'features': [
            '✅ Покупка билетов',
            '✅ Создание компаний',
            '✅ Инвестирование',
            '✅ Все функции экономики',
            '✅ Сберегательные счета',
            '✅ Чеки и переводы'
        ]
    },
    'premium': {
        'name': 'Премиум',
        'price_one_time': 200,
        'price_monthly': 50,
        'features': [
            '✅ Все функции Базового',
            '⭐ +20% к ежедневной зарплате',
            '⭐ -50% комиссия на переводы',
            '⭐ Приоритетная поддержка',
            '⭐ Ранний доступ к новым функциям',
            '🎮 **ДОПОЛНИТЕЛЬНО:**',
            '• 📡 IP адрес игрового сервера',
            '• 📁 Файлы для настройки игры',
            '• 🔧 Техническая поддержка 24/7'
        ],
        'server_ip': '185.231.154.74:25565',  # Пример IP сервера
        'files': ['client_mods.zip', 'config.txt']
    }
}

SALARY_TAX_PERCENT = 13
MINIMUM_WAGE = 16242
MIN_SAVINGS_DEPOSIT = 1000
SAVINGS_INTEREST_RATE = 5.0
CHECK_EXPIRY_DAYS = 30

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
def init_database():
    db_path = os.path.join(os.path.dirname(__file__), 'economy.db')
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance INTEGER DEFAULT 0,
        daily_salary INTEGER DEFAULT 0,
        last_salary_date TEXT,
        has_server_status BOOLEAN DEFAULT 0,
        server_status_type TEXT DEFAULT 'basic',
        server_status_expiry TEXT,
        salary_bonus_percent INTEGER DEFAULT 0,
        transfer_discount_percent INTEGER DEFAULT 0,
        received_server_ip BOOLEAN DEFAULT 0,
        received_server_files BOOLEAN DEFAULT 0,
        registered_date TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        company_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        date TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT UNIQUE,
        file_data BLOB,
        file_size INTEGER,
        description TEXT,
        version TEXT,
        upload_date TEXT DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT 1
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_config (
        id INTEGER PRIMARY KEY,
        server_ip TEXT DEFAULT '185.231.154.74:25565',
        server_name TEXT DEFAULT 'Экономический сервер',
        motd TEXT DEFAULT 'Добро пожаловать!',
        max_players INTEGER DEFAULT 100,
        updated_date TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        tag TEXT UNIQUE,
        owner_id INTEGER,
        balance INTEGER DEFAULT 0,
        capital INTEGER DEFAULT 0,
        shares INTEGER DEFAULT 1000,
        share_price INTEGER DEFAULT 100,
        is_transport_company BOOLEAN DEFAULT 0,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shareholders (
        user_id INTEGER,
        company_id INTEGER,
        shares INTEGER DEFAULT 0,
        investment INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, company_id),
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        route_number TEXT,
        from_city TEXT,
        to_city TEXT,
        departure_time TEXT,
        arrival_time TEXT,
        price INTEGER,
        commission_percent INTEGER DEFAULT 10,
        available_seats INTEGER DEFAULT 100,
        total_seats INTEGER DEFAULT 100,
        is_active BOOLEAN DEFAULT 1,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_number TEXT UNIQUE,
        route_id INTEGER,
        user_id INTEGER,
        company_id INTEGER,
        price_paid INTEGER,
        commission_amount INTEGER,
        seat_number TEXT,
        purchase_date TEXT DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'active',
        qr_code_data TEXT,
        FOREIGN KEY (route_id) REFERENCES routes (id),
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS savings_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        account_number TEXT UNIQUE,
        balance INTEGER DEFAULT 0,
        interest_rate FLOAT DEFAULT 5.0,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP,
        last_interest_date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_number TEXT UNIQUE,
        from_user_id INTEGER,
        to_user_id INTEGER,
        amount INTEGER,
        description TEXT,
        status TEXT DEFAULT 'pending',
        created_date TEXT DEFAULT CURRENT_TIMESTAMP,
        expiry_date TEXT,
        paid_date TEXT,
        FOREIGN KEY (from_user_id) REFERENCES users (user_id),
        FOREIGN KEY (to_user_id) REFERENCES users (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS taxes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tax_type TEXT,
        amount INTEGER,
        period TEXT,
        paid_date TEXT,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        status_type TEXT DEFAULT 'basic',
        payment_type TEXT,
        purchase_date TEXT DEFAULT CURRENT_TIMESTAMP,
        expiry_date TEXT,
        payment_method TEXT,
        payment_amount INTEGER,
        payment_proof TEXT,
        status TEXT DEFAULT 'active',
        auto_renew BOOLEAN DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payment_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_method TEXT UNIQUE,
        details TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )''')
    
    cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_IDS[0],))
    cursor.execute('INSERT OR IGNORE INTO server_config (id) VALUES (1)')
    
    conn.commit()
    return conn, cursor

conn, cursor = init_database()

# ========== ПОМОЩНИКИ ==========
def is_admin(user_id):
    return user_id in ADMIN_IDS

def format_money(amount):
    return f"{amount:,} ₽".replace(",", " ")

def get_user_balance(user_id):
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def update_user_balance(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def calculate_tax(salary_amount):
    taxable_amount = max(salary_amount, MINIMUM_WAGE)
    tax_amount = int(taxable_amount * SALARY_TAX_PERCENT / 100)
    return tax_amount

def log_transaction(user_id, company_id, amount, tr_type, description):
    cursor.execute('INSERT INTO transactions (user_id, company_id, amount, type, description) VALUES (?, ?, ?, ?, ?)',
                   (user_id, company_id, amount, tr_type, description))
    conn.commit()

def check_server_status(user_id):
    cursor.execute('SELECT status_type, expiry_date, payment_type FROM server_statuses WHERE user_id = ? AND status = "active" ORDER BY purchase_date DESC LIMIT 1', (user_id,))
    status = cursor.fetchone()
    
    if not status:
        return False, None, None, None
    
    status_type, expiry_date, payment_type = status
    
    if expiry_date and expiry_date != 'permanent':
        try:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            if datetime.now() > expiry:
                cursor.execute('UPDATE server_statuses SET status = "expired" WHERE user_id = ? AND status = "active"', (user_id,))
                cursor.execute('UPDATE users SET has_server_status = 0 WHERE user_id = ?', (user_id,))
                conn.commit()
                return False, None, None, None
        except:
            pass
    
    return True, status_type, expiry_date, payment_type

def get_status_price(status_type, payment_type):
    if status_type not in STATUS_TYPES:
        return 0
    if payment_type == 'one_time':
        return STATUS_TYPES[status_type]['price_one_time']
    elif payment_type == 'monthly':
        return STATUS_TYPES[status_type]['price_monthly']
    return 0

# ========== КОМАНДЫ СТАТУСОВ ==========
async def server_status_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    has_status, status_type, expiry_date, payment_type = check_server_status(user_id)
    
    text = "🎮 **СТАТУС НА СЕРВЕРЕ**\n\n"
    
    if has_status:
        status_info = STATUS_TYPES.get(status_type, {})
        status_name = status_info.get('name', 'Неизвестный')
        
        if expiry_date == 'permanent':
            expiry_text = "Навсегда 🏆"
            days_left = "∞"
        elif expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            expiry_text = expiry.strftime('%d.%m.%Y')
            days_left = (expiry - datetime.now()).days
        else:
            expiry_text = "Не указана"
            days_left = "?"
        
        payment_type_text = "Единоразово" if payment_type == 'one_time' else "Ежемесячно"
        
        text += f"✅ **У вас есть статус!**\n\n"
        text += f"📊 Тип: {status_name}\n"
        text += f"💳 Оплата: {payment_type_text}\n"
        text += f"📅 Действует до: {expiry_text}\n"
        
        if days_left != "∞" and days_left != "?":
            text += f"⏳ Осталось дней: {days_left}\n"
        
        text += f"\n🎫 **ДОСТУП К ФУНКЦИЯМ:**\n"
        for feature in status_info.get('features', []):
            text += f"{feature}\n"
        
        # Показываем доступные бонусы для премиума
        if status_type == 'premium':
            cursor.execute('SELECT received_server_ip, received_server_files FROM users WHERE user_id = ?', (user_id,))
            user_data = cursor.fetchone()
            if user_data:
                received_ip, received_files = user_data
                
                text += f"\n🎁 **БОНУСЫ ПРЕМИУМ:**\n"
                
                # IP сервера
                cursor.execute('SELECT server_ip, server_name FROM server_config WHERE id = 1')
                server_config = cursor.fetchone()
                if server_config:
                    server_ip, server_name = server_config
                    if received_ip:
                        text += f"📡 IP сервера: ✅ Получен\n"
                        text += f"   🎮 {server_name}\n"
                        text += f"   🌐 {server_ip}\n"
                    else:
                        text += f"📡 IP сервера: ❌ Не получен\n"
                        text += f"   🎯 Получить: /get_server_ip\n"
                
                # Файлы сервера
                cursor.execute('SELECT COUNT(*) FROM server_files WHERE is_active = 1')
                files_count = cursor.fetchone()[0]
                
                if received_files:
                    text += f"📁 Файлы для игры: ✅ Получены ({files_count} файлов)\n"
                    text += f"   📥 Скачать: /get_server_files\n"
                else:
                    text += f"📁 Файлы для игры: ❌ Не получены\n"
                    text += f"   🎯 Получить: /get_server_files\n"
        
        text += f"\n🔄 **ДЕЙСТВИЯ:**\n"
        text += f"/upgrade_status - Улучшить статус\n"
        if status_type == 'basic' and payment_type == 'monthly':
            text += f"/cancel_auto_renew - Отключить авто-продление\n"
        
    else:
        text += f"❌ **У вас нет статуса на сервере!**\n\n"
        text += f"🚫 **Без статуса вы НЕ МОЖЕТЕ:**\n"
        text += f"• Покупать билеты на поезда\n"
        text += f"• Создавать компаний\n"
        text += f"• Инвестировать в акции\n"
        text += f"• Использовать полную экономику\n\n"
        
        text += f"💰 **ДОСТУПНЫЕ СТАТУСЫ:**\n"
        
        for status_key, status_info in STATUS_TYPES.items():
            name = status_info['name']
            one_time = status_info['price_one_time']
            monthly = status_info['price_monthly']
            
            text += f"\n**{name}:**\n"
            text += f"• {format_money(one_time)}₽ - навсегда\n"
            text += f"• {format_money(monthly)}₽ - в месяц\n"
            
            if status_key == 'premium':
                text += f"  🎁 Включает IP сервера и файлы!\n"
        
        text += f"\n🛒 Купить: /buy_server_status\n"
        text += f"💳 Реквизиты: /payment_details"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def get_server_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить IP сервера (для премиум пользователей)"""
    user_id = update.effective_user.id
    
    has_status, status_type, _, _ = check_server_status(user_id)
    
    if not has_status or status_type != 'premium':
        await update.message.reply_text(
            "❌ **ДОСТУП ЗАПРЕЩЕН!**\n\n"
            "IP сервера доступен только для пользователей с **Премиум статусом**.\n\n"
            "⭐ **Премиум статус включает:**\n"
            f"• {format_money(STATUS_TYPES['premium']['price_one_time'])}₽ - навсегда\n"
            f"• {format_money(STATUS_TYPES['premium']['price_monthly'])}₽ - в месяц\n"
            f"• IP адрес игрового сервера\n"
            f"• Файлы для настройки\n"
            f"• Все бонусы Базового статуса\n\n"
            f"🛒 Купить: /buy_server_status"
        )
        return
    
    # Проверяем, получал ли уже пользователь IP
    cursor.execute('SELECT received_server_ip FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()
    
    if user_data and user_data[0]:
        await update.message.reply_text(
            "⚠️ **ВЫ УЖЕ ПОЛУЧАЛИ IP СЕРВЕРА**\n\n"
            "Проверьте историю сообщений с ботом.\n"
            "Если потеряли IP, напишите администратору."
        )
        return
    
    # Получаем IP сервера из конфига
    cursor.execute('SELECT server_ip, server_name, motd FROM server_config WHERE id = 1')
    server_config = cursor.fetchone()
    
    if not server_config:
        await update.message.reply_text(
            "❌ **СЕРВЕР НЕ НАСТРОЕН**\n\n"
            "Администратор еще не настроил сервер.\n"
            "Пожалуйста, подождите или свяжитесь с админом."
        )
        return
    
    server_ip, server_name, motd = server_config
    
    # Отправляем IP пользователю
    ip_message = (
        f"🎮 **ДАННЫЕ ИГРОВОГО СЕРВЕРА**\n\n"
        f"🏆 Статус: Премиум\n"
        f"👤 Игрок: @{update.effective_user.username}\n"
        f"📅 Дата выдачи: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📡 **СЕРВЕР:**\n"
        f"🎯 Название: {server_name}\n"
        f"🌐 IP адрес: `{server_ip}`\n"
        f"📝 MOTD: {motd}\n\n"
        f"⚙️ **КАК ПОДКЛЮЧИТЬСЯ:**\n"
        f"1. Запустите игру\n"
        f"2. Нажмите 'Мультиплеер'\n"
        f"3. 'Добавить сервер'\n"
        f"4. Введите IP: `{server_ip}`\n"
        f"5. Сохраните и подключитесь\n\n"
        f"📁 **ФАЙЛЫ ДЛЯ ИГРЫ:**\n"
        f"Скачать моды и конфиги: /get_server_files\n\n"
        f"⚠️ **ВАЖНО:**\n"
        f"• Не передавайте IP третьим лицам\n"
        f"• При проблемах пишите администратору\n"
        f"• Удачного gaming! 🎯"
    )
    
    try:
        await update.message.reply_text(ip_message, parse_mode='Markdown')
        
        # Отмечаем что пользователь получил IP
        cursor.execute('UPDATE users SET received_server_ip = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        
        # Логируем
        log_transaction(user_id, None, 0, 'получение_ip', f"Получен IP сервера: {server_ip}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки IP: {e}")
        await update.message.reply_text("❌ Ошибка отправки данных. Попробуйте позже.")

async def get_server_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить файлы сервера (для премиум пользователей)"""
    user_id = update.effective_user.id
    
    has_status, status_type, _, _ = check_server_status(user_id)
    
    if not has_status or status_type != 'premium':
        await update.message.reply_text(
            "❌ **ДОСТУП ЗАПРЕЩЕН!**\n\n"
            "Файлы сервера доступны только для пользователей с **Премиум статусом**."
        )
        return
    
    # Получаем список файлов
    cursor.execute('SELECT filename, description, file_size FROM server_files WHERE is_active = 1 ORDER BY filename')
    files = cursor.fetchall()
    
    if not files:
        await update.message.reply_text(
            "📁 **ФАЙЛЫ СЕРВЕРА**\n\n"
            "❌ Файлы еще не загружены администратором.\n"
            "Пожалуйста, подождите или свяжитесь с админом."
        )
        return
    
    text = f"📁 **ФАЙЛЫ ДЛЯ ИГРЫ**\n\n"
    text += f"👤 Игрок: @{update.effective_user.username}\n"
    text += f"🏆 Статус: Премиум\n"
    text += f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n\n"
    
    text += f"📋 **ДОСТУПНЫЕ ФАЙЛЫ ({len(files)}):**\n\n"
    
    for filename, description, file_size in files:
        size_mb = file_size / (1024 * 1024) if file_size else 0
        text += f"📄 **{filename}**\n"
        text += f"   📝 {description}\n"
        text += f"   💾 {size_mb:.1f} MB\n"
        text += f"   📥 /download_{filename.replace('.', '_')}\n\n"
    
    text += f"⚙️ **ИНСТРУКЦИЯ:**\n"
    text += f"1. Скачайте нужные файлы\n"
    text += f"2. Распакуйте в папку игры\n"
    text += f"3. Перезапустите игру\n"
    text += f"4. Подключитесь к серверу\n\n"
    
    text += f"🌐 IP сервера: /get_server_ip\n"
    text += f"🆘 Помощь: @админ (напишите администратору)"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== АДМИН КОМАНДЫ ДЛЯ ФАЙЛОВ ==========
async def admin_server_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель управления файлами сервера"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📁 Управление файлами", callback_data="admin_manage_files")],
        [InlineKeyboardButton("🌐 Настройка IP сервера", callback_data="admin_server_ip")],
        [InlineKeyboardButton("📊 Статистика выдачи", callback_data="admin_files_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 **АДМИН ПАНЕЛЬ ФАЙЛОВ СЕРВЕРА**\n\n"
        "Управление файлами и IP для премиум пользователей:",
        reply_markup=reply_markup
    )

async def admin_manage_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление файлами"""
    query = update.callback_query
    await query.answer()
    
    cursor.execute('SELECT filename, description, file_size, upload_date FROM server_files WHERE is_active = 1 ORDER BY filename')
    files = cursor.fetchall()
    
    text = "📁 **УПРАВЛЕНИЕ ФАЙЛАМИ**\n\n"
    
    if files:
        text += f"📊 Всего файлов: {len(files)}\n\n"
        
        for filename, description, file_size, upload_date in files:
            size_mb = file_size / (1024 * 1024) if file_size else 0
            upload = datetime.strptime(upload_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m')
            
            text += f"📄 **{filename}**\n"
            text += f"   📝 {description}\n"
            text += f"   💾 {size_mb:.1f} MB\n"
            text += f"   📅 {upload}\n"
            text += f"   🗑️ /delete_file_{filename.replace('.', '_')}\n\n"
    else:
        text += "❌ Нет загруженных файлов\n\n"
    
    text += "💾 **КОМАНДЫ:**\n"
    text += "/upload_file - Загрузить новый файл\n"
    text += "Пример: отправьте файл с подписью 'config.txt Основной конфиг'\n\n"
    
    text += "📥 **СКАЧИВАНИЕ:**\n"
    text += "Пользователи премиума могут скачивать файлы командой /get_server_files"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def admin_server_ip_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройка IP сервера"""
    query = update.callback_query
    await query.answer()
    
    cursor.execute('SELECT server_ip, server_name, motd, max_players FROM server_config WHERE id = 1')
    config = cursor.fetchone()
    
    if config:
        server_ip, server_name, motd, max_players = config
        text = (
            f"🌐 **НАСТРОЙКА СЕРВЕРА**\n\n"
            f"📡 Текущие настройки:\n"
            f"• IP: `{server_ip}`\n"
            f"• Название: {server_name}\n"
            f"• MOTD: {motd}\n"
            f"• Макс. игроков: {max_players}\n\n"
            f"⚙️ **КОМАНДЫ ДЛЯ ИЗМЕНЕНИЯ:**\n"
            f"/set_server_ip новый_ip:порт\n"
            f"/set_server_name новое_название\n"
            f"/set_server_motd новое_приветствие\n"
            f"/set_max_players число\n\n"
            f"📊 **СТАТИСТИКА:**\n"
            f"Кто получил IP: /ip_stats"
        )
    else:
        text = "❌ Конфиг сервера не найден"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def set_server_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить IP сервера"""
    if not is_admin(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /set_server_ip ip:порт\nПример: /set_server_ip 185.231.154.74:25565")
        return
    
    new_ip = context.args[0]
    
    cursor.execute('UPDATE server_config SET server_ip = ?, updated_date = ? WHERE id = 1', 
                   (new_ip, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **IP СЕРВЕРА ОБНОВЛЕН!**\n\n"
        f"📡 Новый IP: `{new_ip}`\n"
        f"📅 Дата изменения: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Теперь премиум пользователи будут получать этот IP."
    )

async def set_server_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить название сервера"""
    if not is_admin(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /set_server_name название\nПример: /set_server_name Экономический рай")
        return
    
    new_name = ' '.join(context.args)
    
    cursor.execute('UPDATE server_config SET server_name = ?, updated_date = ? WHERE id = 1', 
                   (new_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    
    await update.message.reply_text(f"✅ Название сервера изменено на: {new_name}")

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загрузки файлов"""
    if not is_admin(update.effective_user.id):
        return
    
    if not update.message.document and not update.message.photo:
        return
    
    user_id = update.effective_user.id
    
    # Получаем описание файла из подписи
    caption = update.message.caption or ""
    parts = caption.split(' ', 1)
    
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ **УКАЖИТЕ ОПИСАНИЕ ФАЙЛА!**\n\n"
            "Отправьте файл с подписью в формате:\n"
            "`имя_файла.расширение Описание файла`\n\n"
            "Пример: `client_mods.zip Моды для клиента`"
        )
        return
    
    filename = parts[0].strip()
    description = parts[1].strip()
    
    try:
        if update.message.document:
            file = await update.message.document.get_file()
            file_size = update.message.document.file_size
        else:
            # Если фото, берем самое большое
            photo = update.message.photo[-1]
            file = await photo.get_file()
            file_size = photo.file_size
        
        # Скачиваем файл
        file_data = await file.download_as_bytearray()
        
        # Сохраняем в базу
        cursor.execute('''
            INSERT OR REPLACE INTO server_files (filename, file_data, file_size, description)
            VALUES (?, ?, ?, ?)
        ''', (filename, bytes(file_data), file_size, description))
        
        conn.commit()
        
        size_mb = file_size / (1024 * 1024)
        
        await update.message.reply_text(
            f"✅ **ФАЙЛ ЗАГРУЖЕН!**\n\n"
            f"📄 Имя: {filename}\n"
            f"📝 Описание: {description}\n"
            f"💾 Размер: {size_mb:.1f} MB\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Теперь премиум пользователи могут скачать этот файл."
        )
        
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        await update.message.reply_text(f"❌ Ошибка загрузки файла: {str(e)}")

async def ip_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика выдачи IP"""
    if not is_admin(update.effective_user.id):
        return
    
    cursor.execute('''
        SELECT u.username, ss.status_type, u.received_server_ip, u.received_server_files,
               ss.purchase_date, ss.expiry_date
        FROM users u
        JOIN server_statuses ss ON u.user_id = ss.user_id
        WHERE ss.status = 'active' AND ss.status_type = 'premium'
        ORDER BY ss.purchase_date DESC
    ''')
    
    premium_users = cursor.fetchall()
    
    text = "📊 **СТАТИСТИКА ВЫДАЧИ ПРЕМИУМ**\n\n"
    
    if premium_users:
        total = len(premium_users)
        received_ip = sum(1 for u in premium_users if u[2])
        received_files = sum(1 for u in premium_users if u[3])
        
        text += f"👥 Всего премиум пользователей: {total}\n"
        text += f"📡 Получили IP: {received_ip}\n"
        text += f"📁 Получили файлы: {received_files}\n\n"
        
        text += "👤 **СПИСОК ПОЛЬЗОВАТЕЛЕЙ:**\n"
        for username, status_type, got_ip, got_files, purchase_date, expiry_date in premium_users[:10]:
            purchase = datetime.strptime(purchase_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m')
            
            text += f"• @{username}\n"
            text += f"  🛒 {purchase} | "
            text += f"📡{'✅' if got_ip else '❌'} | "
            text += f"📁{'✅' if got_files else '❌'}\n"
        
        if total > 10:
            text += f"\n... и еще {total - 10} пользователей"
    else:
        text += "❌ Нет премиум пользователей\n"
    
    await update.message.reply_text(text)

# ========== ОБНОВЛЕННЫЙ HELP ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    help_text = "📚 **КОМАНДЫ БОТА**\n\n"
    
    help_text += "🎮 **СТАТУС НА СЕРВЕРЕ:**\n"
    help_text += "/server_status_info - Информация о статусе\n"
    help_text += "/buy_server_status - Купить статус\n"
    help_text += "/payment_details - Реквизиты для оплаты\n"
    help_text += "/upgrade_status - Улучшить статус\n"
    help_text += "/get_server_ip - Получить IP сервера (премиум)\n"
    help_text += "/get_server_files - Скачать файлы (премиум)\n\n"
    
    help_text += "💰 **ФИНАНСЫ:**\n"
    help_text += "/balance - Баланс\n"
    help_text += "/daily - Зарплата\n"
    help_text += "/my_taxes - Мои налоги\n\n"
    
    help_text += "🏦 **СБЕРЕГАТЕЛЬНЫЕ СЧЕТА:**\n"
    help_text += "/create_savings_account - Открыть счет\n"
    help_text += "/my_savings - Мой счет\n\n"
    
    help_text += "🎫 **ЧЕКИ:**\n"
    help_text += "/create_check сумма описание - Выписать чек\n"
    help_text += "/pay_check НОМЕР - Оплатить чек\n\n"
    
    help_text += "🚂 **БИЛЕТЫ (требуется статус):**\n"
    help_text += "/buy_ticket - Купить билет\n\n"
    
    help_text += "🏢 **КОМПАНИИ (требуется статус):**\n"
    help_text += "/create_company Название TAG\n\n"
    
    if is_admin(user_id):
        help_text += "\n👑 **АДМИН КОМАНДЫ:**\n"
        help_text += "/admin_server_status - Управление статусами\n"
        help_text += "/admin_server_files - Управление файлами\n"
        help_text += "/add_payment метод реквизиты - Реквизиты\n"
        help_text += "/give_status @username - Выдать статус\n"
        help_text += "/set_server_ip ip:порт - Изменить IP\n"
        help_text += "/ip_stats - Статистика выдачи\n"
        help_text += "📁 Загрузить файл: отправьте файл с подписью\n"
    
    help_text += "\n💸 **ЦЕНЫ СТАТУСОВ:**\n"
    help_text += f"• Базовый: {STATUS_TYPES['basic']['price_one_time']}₽ навсегда\n"
    help_text += f"• Базовый: {STATUS_TYPES['basic']['price_monthly']}₽ в месяц\n"
    help_text += f"• Премиум: {STATUS_TYPES['premium']['price_one_time']}₽ навсегда\n"
    help_text += f"• Премиум: {STATUS_TYPES['premium']['price_monthly']}₽ в месяц\n"
    help_text += f"⭐ Премиум включает IP сервера и файлы!"
    
    await update.message.reply_text(help_text)

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ (заглушки) ==========
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Функция зарплаты будет добавлена в следующем обновлении")

async def my_taxes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧾 Функция налогов будет добавлена в следующем обновлении")

async def create_savings_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏦 Функция сберегательных счетов будет добавлена в следующем обновлении")

async def create_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎫 Функция чеков будет добавлена в следующем обновлении")

async def buy_ticket_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    has_status, _, _, _ = check_server_status(user_id)
    
    if not has_status:
        await update.message.reply_text("❌ Для покупки билетов нужен статус на сервере. /buy_server_status")
    else:
        await update.message.reply_text("🚂 Функция покупки билетов будет добавлена в следующем обновлении")

async def create_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    has_status, _, _, _ = check_server_status(user_id)
    
    if not has_status:
        await update.message.reply_text("❌ Для создания компаний нужен статус на сервере. /buy_server_status")
    else:
        await update.message.reply_text("🏢 Функция создания компаний будет добавлена в следующем обновлении")

# ========== ЗАПУСК БОТА ==========
def main():
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        commands = [
            ("start", start),
            ("help", help_command),
            ("balance", balance),
            ("daily", daily),
            ("my_taxes", my_taxes),
            ("create_savings_account", create_savings_account),
            ("create_check", create_check),
            ("server_status_info", server_status_info),
            ("get_server_ip", get_server_ip),
            ("get_server_files", get_server_files),
            ("buy_ticket", buy_ticket_menu),
            ("create_company", create_company),
            ("set_server_ip", set_server_ip),
            ("set_server_name", set_server_name),
            ("ip_stats", ip_stats),
            ("admin_server_files", admin_server_files),
        ]
        
        for command, handler in commands:
            application.add_handler(CommandHandler(command, handler))
        
        # Обработчик загрузки файлов
        application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file_upload))
        
        print("=" * 50)
        print("🤖 БОТ С ПРЕМИУМ СЕРВЕРОМ ЗАПУЩЕН!")
        print(f"💰 Базовый: {STATUS_TYPES['basic']['price_one_time']}₽ навсегда")
        print(f"⭐ Премиум: {STATUS_TYPES['premium']['price_one_time']}₽ навсегда")
        print(f"📡 IP сервера: {STATUS_TYPES['premium'].get('server_ip', 'Не настроен')}")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
