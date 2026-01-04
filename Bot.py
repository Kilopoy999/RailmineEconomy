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
        'price_one_time': 50,     # 50₽ навсегда
        'price_monthly': 10,      # 10₽ в месяц
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
        'price_one_time': 200,    # 200₽ навсегда
        'price_monthly': 50,      # 50₽ в месяц
        'features': [
            '✅ Все функции Базового',
            '⭐ +20% к ежедневной зарплате',
            '⭐ -50% комиссия на переводы',
            '⭐ Приоритетная поддержка',
            '⭐ Ранний доступ к новым функциям'
        ]
    }
}

# Остальные константы остаются
SALARY_TAX_PERCENT = 13
MINIMUM_WAGE = 16242
MIN_SAVINGS_DEPOSIT = 1000
SAVINGS_INTEREST_RATE = 5.0
CHECK_EXPIRY_DAYS = 30

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
def init_database():
    """Инициализация базы данных"""
    db_path = os.path.join(os.path.dirname(__file__), 'economy.db')
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # Таблица пользователей
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
        registered_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица транзакций
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        company_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица компаний
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
    )
    ''')
    
    # Таблица акционеров
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shareholders (
        user_id INTEGER,
        company_id INTEGER,
        shares INTEGER DEFAULT 0,
        investment INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, company_id),
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )
    ''')
    
    # Таблица маршрутов
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
    )
    ''')
    
    # Таблица билетов
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
    )
    ''')
    
    # Таблица сберегательных счетов
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
    )
    ''')
    
    # Таблица чеков
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
    )
    ''')
    
    # Таблица налогов
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
    )
    ''')
    
    # Таблица статусов на сервере (ОБНОВЛЕНА)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        status_type TEXT DEFAULT 'basic',
        payment_type TEXT,  -- 'one_time' или 'monthly'
        purchase_date TEXT DEFAULT CURRENT_TIMESTAMP,
        expiry_date TEXT,
        payment_method TEXT,
        payment_amount INTEGER,
        payment_proof TEXT,
        status TEXT DEFAULT 'active',
        auto_renew BOOLEAN DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Таблица платежных реквизитов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payment_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_method TEXT UNIQUE,
        details TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица админов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
    ''')
    
    # Добавляем вас как админа
    cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_IDS[0],))
    
    conn.commit()
    return conn, cursor

# Инициализация БД
conn, cursor = init_database()

# ========== ПОМОЩНИКИ ==========
def is_admin(user_id):
    """Проверка прав администратора"""
    return user_id in ADMIN_IDS

def format_money(amount):
    """Форматирование денег"""
    return f"{amount:,} ₽".replace(",", " ")

def get_user_balance(user_id):
    """Получить баланс пользователя"""
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def update_user_balance(user_id, amount):
    """Обновить баланс пользователя"""
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def check_server_status(user_id):
    """Проверить наличие статуса на сервере"""
    cursor.execute('''
        SELECT status_type, expiry_date, payment_type
        FROM server_statuses 
        WHERE user_id = ? AND status = 'active'
        ORDER BY purchase_date DESC
        LIMIT 1
    ''', (user_id,))
    
    status = cursor.fetchone()
    
    if not status:
        return False, None, None, None
    
    status_type, expiry_date, payment_type = status
    
    if expiry_date and expiry_date != 'permanent':
        expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
        if datetime.now() > expiry:
            # Статус истек
            cursor.execute('UPDATE server_statuses SET status = "expired" WHERE user_id = ? AND status = "active"', (user_id,))
            cursor.execute('UPDATE users SET has_server_status = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
            return False, None, None, None
    
    return True, status_type, expiry_date, payment_type

def get_status_price(status_type, payment_type):
    """Получить цену статуса"""
    if status_type not in STATUS_TYPES:
        return 0
    
    if payment_type == 'one_time':
        return STATUS_TYPES[status_type]['price_one_time']
    elif payment_type == 'monthly':
        return STATUS_TYPES[status_type]['price_monthly']
    return 0

# ========== СИСТЕМА СТАТУСОВ ==========
async def server_status_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о статусе на сервере"""
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
        
        text += f"\n🔄 **ДЕЙСТВИЯ:**\n"
        text += f"/upgrade_status - Улучшить статус\n"
        if payment_type == 'monthly':
            text += f"/cancel_auto_renew - Отключить авто-продление\n"
        
    else:
        text += f"❌ **У вас нет статуса на сервере!**\n\n"
        text += f"🚫 **Без статуса вы НЕ МОЖЕТЕ:**\n"
        text += f"• Покупать билеты на поезда\n"
        text += f"• Создавать компании\n"
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
        
        text += f"\n🛒 Купить: /buy_server_status\n"
        text += f"💳 Реквизиты: /payment_details"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def buy_server_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Купить статус на сервере"""
    user_id = update.effective_user.id
    
    has_status, current_type, _, _ = check_server_status(user_id)
    
    if has_status:
        await update.message.reply_text(
            "✅ У вас уже есть активный статус!\n"
            "📋 Информация: /server_status_info\n"
            "🔄 Улучшить: /upgrade_status"
        )
        return
    
    # Создаем клавиатуру с вариантами
    keyboard = []
    
    for status_key, status_info in STATUS_TYPES.items():
        name = status_info['name']
        one_time = status_info['price_one_time']
        monthly = status_info['price_monthly']
        
        keyboard.append([
            InlineKeyboardButton(
                f"{name} - {format_money(one_time)}₽ навсегда", 
                callback_data=f"buy_{status_key}_one_time"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                f"{name} - {format_money(monthly)}₽ в месяц", 
                callback_data=f"buy_{status_key}_monthly"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛒 **ВЫБЕРИТЕ СТАТУС**\n\n"
        "Выберите тип статуса и способ оплаты:",
        reply_markup=reply_markup
    )

async def handle_buy_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик покупки статуса"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("buy_"):
        parts = data.split("_")
        if len(parts) == 3:
            status_type = parts[1]
            payment_type = parts[2]
            
            if status_type in STATUS_TYPES and payment_type in ['one_time', 'monthly']:
                await show_payment_details(query, status_type, payment_type)
            else:
                await query.edit_message_text("❌ Ошибка выбора статуса")

async def show_payment_details(query, status_type, payment_type):
    """Показать реквизиты для оплаты"""
    status_info = STATUS_TYPES[status_type]
    status_name = status_info['name']
    price = get_status_price(status_type, payment_type)
    
    payment_type_text = "навсегда" if payment_type == 'one_time' else "в месяц"
    
    # Получаем платежные реквизиты
    cursor.execute('SELECT payment_method, details FROM payment_details WHERE is_active = 1')
    payment_methods = cursor.fetchall()
    
    if not payment_methods:
        await query.edit_message_text(
            "⏳ **ОПЛАТА СТАТУСА**\n\n"
            f"💰 Статус: {status_name}\n"
            f"💳 Способ: {payment_type_text}\n"
            f"🎫 Цена: {format_money(price)}\n\n"
            f"❌ Платежные реквизиты еще не настроены.\n"
            f"Пожалуйста, свяжитесь с администратором."
        )
        return
    
    text = f"🛒 **ПОКУПКА: {status_name}**\n\n"
    text += f"💰 Цена: {format_money(price)}₽ {payment_type_text}\n\n"
    
    if payment_type == 'one_time':
        text += f"⏳ Срок: Навсегда\n"
    else:
        text += f"⏳ Срок: 30 дней (авто-продление)\n"
    
    text += f"\n🎫 **ВКЛЮЧАЕТ:**\n"
    for feature in status_info['features'][:3]:  # Показываем первые 3 фичи
        text += f"• {feature}\n"
    
    text += f"\n💳 **ДОСТУПНЫЕ СПОСОБЫ ОПЛАТЫ:**\n\n"
    
    for method, details in payment_methods:
        text += f"**{method.upper()}:**\n"
        text += f"```\n{details}\n```\n"
    
    text += f"\n📋 **ИНСТРУКЦИЯ:**\n"
    text += f"1. Совершите перевод {format_money(price)}₽\n"
    text += f"2. Сохраните скриншот/чек\n"
    text += f"3. Напишите администратору\n"
    text += f"4. Укажите: @{query.from_user.username} и тип '{status_name} {payment_type_text}'\n"
    text += f"5. Администратор активирует ваш статус\n\n"
    
    text += f"👑 **АДМИНИСТРАТОР:**\n"
    text += f"Напишите в личные сообщения администратору с доказательством оплаты.\n\n"
    
    text += f"🔄 Проверить статус: /server_status_info"
    
    # Сохраняем выбор пользователя
    context.user_data['pending_status'] = {
        'status_type': status_type,
        'payment_type': payment_type,
        'price': price
    }
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать платежные реквизиты"""
    cursor.execute('SELECT payment_method, details FROM payment_details WHERE is_active = 1')
    payment_methods = cursor.fetchall()
    
    if not payment_methods:
        await update.message.reply_text(
            "💳 **ПЛАТЕЖНЫЕ РЕКВИЗИТЫ**\n\n"
            "❌ Реквизиты еще не настроены.\n"
            "Пожалуйста, свяжитесь с администратором."
        )
        return
    
    text = "💳 **РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ**\n\n"
    
    text += "💰 **ДОСТУПНЫЕ СТАТУСЫ:**\n"
    for status_key, status_info in STATUS_TYPES.items():
        name = status_info['name']
        one_time = status_info['price_one_time']
        monthly = status_info['price_monthly']
        
        text += f"\n**{name}:**\n"
        text += f"• {format_money(one_time)}₽ - навсегда\n"
        text += f"• {format_money(monthly)}₽ - в месяц\n"
    
    text += f"\n💸 **ДОСТУПНЫЕ СПОСОБЫ ОПЛАТЫ:**\n\n"
    
    for method, details in payment_methods:
        text += f"**{method.upper()}:**\n"
        text += f"```\n{details}\n```\n\n"
    
    text += "📋 **ИНСТРУКЦИЯ:**\n"
    text += "1. Выберите статус: /buy_server_status\n"
    text += "2. Совершите перевод по реквизитам\n"
    text += "3. Сохраните скриншот/чек\n"
    text += "4. Свяжитесь с администратором\n"
    text += "5. Предоставьте доказательство оплаты\n\n"
    
    text += "🛒 Купить статус: /buy_server_status"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def upgrade_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшить статус"""
    user_id = update.effective_user.id
    
    has_status, current_type, _, payment_type = check_server_status(user_id)
    
    if not has_status:
        await update.message.reply_text(
            "❌ У вас нет статуса!\n"
            "🛒 Купить: /buy_server_status"
        )
        return
    
    if current_type == 'premium':
        await update.message.reply_text(
            "🎉 У вас уже максимальный статус Premium!\n"
            "📋 Информация: /server_status_info"
        )
        return
    
    # Рассчитываем стоимость апгрейда
    current_price = get_status_price('basic', payment_type)
    new_price = get_status_price('premium', payment_type)
    upgrade_price = new_price - current_price
    
    if upgrade_price <= 0:
        upgrade_price = new_price  # На всякий случай
    
    keyboard = [
        [InlineKeyboardButton(f"💳 Оплатить {format_money(upgrade_price)}₽", callback_data="confirm_upgrade")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_upgrade")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔄 **УЛУЧШЕНИЕ СТАТУСА**\n\n"
        f"📊 Текущий: Базовый\n"
        f"⭐ Новый: Премиум\n"
        f"💸 Стоимость улучшения: {format_money(upgrade_price)}₽\n\n"
        f"🎫 **НОВЫЕ ВОЗМОЖНОСТИ:**\n"
        f"• +20% к ежедневной зарплате\n"
        f"• -50% комиссия на переводы\n"
        f"• Приоритетная поддержка\n"
        f"• Ранний доступ к новым функциям\n\n"
        f"Вы хотите улучшить статус?",
        reply_markup=reply_markup
    )

async def handle_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик улучшения статуса"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_upgrade":
        await query.edit_message_text(
            "🔄 **УЛУЧШЕНИЕ СТАТУСА**\n\n"
            "Для улучшения статуса:\n\n"
            "1. Совершите дополнительный платеж\n"
            "2. Свяжитесь с администратором\n"
            "3. Укажите что хотите улучшить статус\n"
            "4. Администратор обновит ваш статус\n\n"
            "💳 Реквизиты: /payment_details\n"
            "👑 Администратор: напишите в ЛС"
        )
    else:
        await query.edit_message_text("❌ Улучшение статуса отменено")

# ========== АДМИН КОМАНДЫ ==========
async def admin_server_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель управления статусами"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    keyboard = [
        [InlineKeyboardButton("💳 Управление реквизитами", callback_data="admin_payment_details")],
        [InlineKeyboardButton("👥 Активные статусы", callback_data="admin_active_statuses")],
        [InlineKeyboardButton("➕ Выдать статус", callback_data="admin_give_status_menu")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_status_stats")],
        [InlineKeyboardButton("🔄 Продлить статус", callback_data="admin_extend_status")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 **АДМИН ПАНЕЛЬ СТАТУСОВ**\n\n"
        "Управление статусами на сервере:",
        reply_markup=reply_markup
    )

async def admin_give_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выдачи статуса"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Базовый навсегда", callback_data="give_basic_permanent")],
        [InlineKeyboardButton("Базовый на месяц", callback_data="give_basic_monthly")],
        [InlineKeyboardButton("Премиум навсегда", callback_data="give_premium_permanent")],
        [InlineKeyboardButton("Премиум на месяц", callback_data="give_premium_monthly")],
        [InlineKeyboardButton("Назад", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "➕ **ВЫДАТЬ СТАТУС**\n\n"
        "Выберите тип статуса для выдачи:",
        reply_markup=reply_markup
    )

async def handle_give_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выдачи статуса"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "give_basic_permanent":
        context.user_data['give_status_type'] = 'basic'
        context.user_data['give_payment_type'] = 'one_time'
        context.user_data['give_days'] = 0
    elif data == "give_basic_monthly":
        context.user_data['give_status_type'] = 'basic'
        context.user_data['give_payment_type'] = 'monthly'
        context.user_data['give_days'] = 30
    elif data == "give_premium_permanent":
        context.user_data['give_status_type'] = 'premium'
        context.user_data['give_payment_type'] = 'one_time'
        context.user_data['give_days'] = 0
    elif data == "give_premium_monthly":
        context.user_data['give_status_type'] = 'premium'
        context.user_data['give_payment_type'] = 'monthly'
        context.user_data['give_days'] = 30
    elif data == "back_to_admin":
        await admin_server_status(update, context)
        return
    
    await query.edit_message_text(
        f"👑 **ВЫДАТЬ СТАТУС**\n\n"
        f"Тип: {context.user_data['give_status_type']}\n"
        f"Способ: {context.user_data['give_payment_type']}\n"
        f"Дней: {context.user_data['give_days'] if context.user_data['give_days'] > 0 else 'Навсегда'}\n\n"
        f"Введите username пользователя:\n"
        f"Пример: @username или user123"
    )

async def give_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды выдачи статуса"""
    if not is_admin(update.effective_user.id):
        return
    
    if 'give_status_type' not in context.user_data:
        await update.message.reply_text("❌ Сначала выберите тип статуса через /admin_server_status")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите username пользователя")
        return
    
    username = context.args[0].replace('@', '')
    status_type = context.user_data['give_status_type']
    payment_type = context.user_data['give_payment_type']
    days = context.user_data['give_days']
    
    # Находим пользователя
    cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    
    if not user:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден")
        return
    
    user_id = user[0]
    
    # Определяем дату окончания
    if days == 0:
        expiry_date = 'permanent'
        expiry_text = "навсегда"
    else:
        expiry_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        expiry_text = f"на {days} дней"
    
    # Проверяем, есть ли уже статус
    cursor.execute('SELECT id FROM server_statuses WHERE user_id = ? AND status = "active"', (user_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Обновляем существующий
        cursor.execute('''
            UPDATE server_statuses 
            SET status_type = ?, 
                payment_type = ?,
                expiry_date = ?,
                status = 'active',
                purchase_date = ?
            WHERE user_id = ?
        ''', (status_type, payment_type, expiry_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))
    else:
        # Создаем новый
        cursor.execute('''
            INSERT INTO server_statuses (user_id, status_type, payment_type, expiry_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, status_type, payment_type, expiry_date))
    
    # Обновляем флаг и бонусы у пользователя
    salary_bonus = 20 if status_type == 'premium' else 0
    transfer_discount = 50 if status_type == 'premium' else 0
    
    cursor.execute('''
        UPDATE users 
        SET has_server_status = 1, 
            server_status_type = ?,
            salary_bonus_percent = ?,
            transfer_discount_percent = ?
        WHERE user_id = ?
    ''', (status_type, salary_bonus, transfer_discount, user_id))
    
    conn.commit()
    
    # Уведомляем пользователя
    status_info = STATUS_TYPES[status_type]
    status_name = status_info['name']
    
    try:
        await context.bot.send_message(
            user_id,
            f"🎉 **ВЫ ПОЛУЧИЛИ СТАТУС НА СЕРВЕРЕ!**\n\n"
            f"👑 От: администратор\n"
            f"📊 Тип: {status_name}\n"
            f"💳 Способ: {'Единоразово' if payment_type == 'one_time' else 'Ежемесячно'}\n"
            f"📅 Срок: {expiry_text}\n\n"
            f"✅ **Теперь вы можете:**\n"
            for feature in status_info['features'][:3]:
                f"• {feature}\n"
            f"\n📋 Проверить статус: /server_status_info"
        )
    except:
        pass
    
    await update.message.reply_text(
        f"✅ **СТАТУС ВЫДАН!**\n\n"
        f"👤 Пользователь: @{username}\n"
        f"📊 Тип: {status_name}\n"
        f"💳 Способ: {'Единоразово' if payment_type == 'one_time' else 'Ежемесячно'}\n"
        f"📅 Срок: {expiry_text}\n"
        f"🆔 ID: {user_id}"
    )
    
    # Очищаем данные
    context.user_data.pop('give_status_type', None)
    context.user_data.pop('give_payment_type', None)
    context.user_data.pop('give_days', None)

async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить платежные реквизиты"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Использование: /add_payment метод реквизиты\n"
            "Пример: /add_payment Сбербанк 2202 2002 1234 5678 Иванов Иван\n"
            "Пример: /add_payment Тинькофф 5536 9138 1234 5678\n"
            "Пример: /add_payment СБП +79123456789"
        )
        return
    
    payment_method = context.args[0]
    payment_details = ' '.join(context.args[1:])
    
    # Проверяем, есть ли уже такой метод
    cursor.execute('SELECT id FROM payment_details WHERE payment_method = ?', (payment_method,))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('UPDATE payment_details SET details = ? WHERE payment_method = ?', (payment_details, payment_method))
        action = "обновлены"
    else:
        cursor.execute('INSERT INTO payment_details (payment_method, details) VALUES (?, ?)', (payment_method, payment_details))
        action = "добавлены"
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **ПЛАТЕЖНЫЕ РЕКВИЗИТЫ {action.upper()}!**\n\n"
        f"💳 Метод: {payment_method}\n"
        f"📋 Реквизиты: ```{payment_details}```\n\n"
        f"Теперь пользователи смогут видеть эти реквизиты при покупке статуса."
    )

async def admin_active_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активные статусы"""
    query = update.callback_query
    await query.answer()
    
    cursor.execute('''
        SELECT u.username, ss.status_type, ss.payment_type, ss.expiry_date, ss.purchase_date
        FROM server_statuses ss
        JOIN users u ON ss.user_id = u.user_id
        WHERE ss.status = 'active'
        ORDER BY ss.expiry_date IS NULL, ss.expiry_date DESC
    ''')
    
    statuses = cursor.fetchall()
    
    text = "👥 **АКТИВНЫЕ СТАТУСЫ**\n\n"
    
    if statuses:
        basic_count = 0
        premium_count = 0
        permanent_count = 0
        monthly_count = 0
        
        for username, status_type, payment_type, expiry_date, purchase_date in statuses[:10]:  # Показываем первые 10
            status_name = STATUS_TYPES.get(status_type, {}).get('name', 'Неизвестный')
            payment_text = "навсегда" if payment_type == 'one_time' else "месячный"
            
            if expiry_date == 'permanent':
                expiry_text = "Навсегда"
                permanent_count += 1
            elif expiry_date:
                expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
                expiry_text = expiry.strftime('%d.%m')
                days_left = (expiry - datetime.now()).days
                expiry_text += f" ({days_left} дн.)"
                monthly_count += 1
            else:
                expiry_text = "Не указана"
            
            if status_type == 'basic':
                basic_count += 1
            else:
                premium_count += 1
            
            purchase = datetime.strptime(purchase_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m')
            
            text += f"👤 **@{username}**\n"
            text += f"   {status_name} | {payment_text}\n"
            text += f"   📅 {expiry_text} | 🛒 {purchase}\n\n"
        
        if len(statuses) > 10:
            text += f"... и еще {len(statuses) - 10} статусов\n\n"
        
        text += f"📊 **СТАТИСТИКА:**\n"
        text += f"• Всего активных: {len(statuses)}\n"
        text += f"• Базовых: {basic_count}\n"
        text += f"• Премиум: {premium_count}\n"
        text += f"• Навсегда: {permanent_count}\n"
        text += f"• Месячных: {monthly_count}\n"
    else:
        text += "❌ Нет активных статусов\n"
    
    text += f"\n💰 **ЦЕНЫ:**\n"
    text += f"• Базовый: {format_money(STATUS_TYPES['basic']['price_one_time'])}₽ навсегда\n"
    text += f"• Базовый: {format_money(STATUS_TYPES['basic']['price_monthly'])}₽ в месяц\n"
    text += f"• Премиум: {format_money(STATUS_TYPES['premium']['price_one_time'])}₽ навсегда\n"
    text += f"• Премиум: {format_money(STATUS_TYPES['premium']['price_monthly'])}₽ в месяц"
    
    await query.edit_message_text(text, parse_mode='Markdown')

# ========== ОБНОВЛЕННЫЕ ФУНКЦИИ С ПРОВЕРКОЙ СТАТУСА ==========
async def buy_ticket_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню покупки билетов (с проверкой статуса)"""
    user_id = update.effective_user.id
    
    # Проверяем статус на сервере
    has_status, _, _, _ = check_server_status(user_id)
    
    if not has_status:
        await update.message.reply_text(
            "❌ **ДОСТУП ЗАПРЕЩЕН!**\n\n"
            "Для покупки билетов необходим статус на сервере.\n\n"
            "💰 **ДОСТУПНЫЕ ВАРИАНТЫ:**\n"
            f"• Базовый: {format_money(STATUS_TYPES['basic']['price_one_time'])}₽ навсегда\n"
            f"• Базовый: {format_money(STATUS_TYPES['basic']['price_monthly'])}₽ в месяц\n\n"
            "🎮 Проверить статус: /server_status_info\n"
            "🛒 Купить статус: /buy_server_status\n"
            "💳 Реквизиты: /payment_details"
        )
        return
    
    # Если есть статус, показываем меню покупки билетов
    await update.message.reply_text(
        "🚂 **ПОКУПКА БИЛЕТОВ**\n\n"
        "✅ Статус на сервере: АКТИВЕН\n"
        "🎫 Вы можете покупать билеты!\n\n"
        "⚠️ Функция покупки билетов будет доступна в следующем обновлении.\n"
        "Сначала нужно настроить транспортные компании и маршруты."
    )

async def create_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать компанию (с проверкой статуса)"""
    user_id = update.effective_user.id
    
    # Проверяем статус на сервере
    has_status, _, _, _ = check_server_status(user_id)
    
    if not has_status:
        await update.message.reply_text(
            "❌ **ДОСТУП ЗАПРЕЩЕН!**\n\n"
            "Для создания компаний необходим статус на сервере.\n\n"
            "💰 **ДОСТУПНЫЕ ВАРИАНТЫ:**\n"
            f"• Базовый: {format_money(STATUS_TYPES['basic']['price_one_time'])}₽ навсегда\n"
            f"• Базовый: {format_money(STATUS_TYPES['basic']['price_monthly'])}₽ в месяц\n\n"
            "🎮 Проверить статус: /server_status_info\n"
            "🛒 Купить статус: /buy_server_status"
        )
        return
    
    # Если есть статус, продолжаем создание компании
    await update.message.reply_text(
        "🏢 **СОЗДАНИЕ КОМПАНИИ**\n\n"
        "✅ Статус на сервере: АКТИВЕН\n"
        "🚀 Вы можете создавать компании!\n\n"
        "⚠️ Функция создания компаний будет доступна в следующем обновлении.\n"
        "Сначала нужно донастроить экономическую систему."
    )

# ========== ОБНОВЛЕННЫЙ HELP ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь по командам"""
    user_id = update.effective_user.id
    
    help_text = "📚 **КОМАНДЫ БОТА**\n\n"
    
    help_text += "🎮 **СТАТУС НА СЕРВЕРЕ:**\n"
    help_text += "/server_status_info - Информация о статусе\n"
    help_text += "/buy_server_status - Купить статус\n"
    help_text += "/payment_details - Реквизиты для оплаты\n"
    help_text += "/upgrade_status - Улучшить статус\n\n"
    
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
        help_text += "/add_payment метод реквизиты - Добавить реквизиты\n"
        help_text += "/give_status @username - Выдать статус\n"
    
    help_text += "\n💸 **ЦЕНЫ СТАТУСОВ:**\n"
    help_text += f"• Базовый: {format_money(STATUS_TYPES['basic']['price_one_time'])}₽ навсегда\n"
    help_text += f"• Базовый: {format_money(STATUS_TYPES['basic']['price_monthly'])}₽ в месяц\n"
    help_text += f"• Премиум: {format_money(STATUS_TYPES['premium']['price_one_time'])}₽ навсегда\n"
    help_text += f"• Премиум: {format_money(STATUS_TYPES['premium']['price_monthly'])}₽ в месяц"
    
    await update.message.reply_text(help_text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда старт"""
    user = update.effective_user
    user_id = user.id
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)',
                      (user_id, user.username, user.full_name))
        conn.commit()
        
        welcome_text = (
            f"👋 Привет, {user.full_name}!\n\n"
            f"🏦 **ЭКОНОМИЧЕСКАЯ СИСТЕМА**\n\n"
            f"💰 **ДОСТУП К ФУНКЦИЯМ:**\n"
            f"Для доступа к полной экономике нужен статус:\n\n"
            f"🎮 **БАЗОВЫЙ СТАТУС:**\n"
            f"• {format_money(STATUS_TYPES['basic']['price_one_time'])}₽ - навсегда\n"
            f"• {format_money(STATUS_TYPES['basic']['price_monthly'])}₽ - в месяц\n\n"
            f"✅ **ВКЛЮЧАЕТ:**\n"
            f"• Покупку билетов на поезда\n"
            f"• Создание компаний\n"
            f"• Инвестирование\n"
            f"• Все функции экономики\n\n"
            f"🛒 Купить статус: /buy_server_status\n"
            f"📋 Подробнее: /server_status_info\n"
            f"📚 Все команды: /help"
        )
        
        await update.message.reply_text(welcome_text)
    else:
        await update.message.reply_text(f"С возвращением, {user.full_name}!")

# ========== ОБРАБОТЧИКИ КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий кнопок"""
    query = update.callback_query
    
    try:
        await query.answer()
        
        data = query.data
        
        if data.startswith("buy_"):
            await handle_buy_status(update, context)
        elif data.startswith("give_"):
            await handle_give_status(update, context)
        elif data == "admin_payment_details":
            await query.edit_message_text(
                "💳 **УПРАВЛЕНИЕ РЕКВИЗИТАМИ**\n\n"
                "Добавить реквизиты:\n"
                "`/add_payment метод реквизиты`\n\n"
                "Примеры:\n"
                "• `/add_payment Сбербанк 2202 2002 1234 5678`\n"
                "• `/add_payment Тинькофф 5536 9138 1234 5678`\n"
                "• `/add_payment СБП +79123456789`\n\n"
                "Просмотреть реквизиты: /payment_details"
            )
        elif data == "admin_active_statuses":
            await admin_active_statuses(update, context)
        elif data == "admin_give_status_menu":
            await admin_give_status_menu(update, context)
        elif data == "admin_status_stats":
            await query.edit_message_text("📊 Статистика будет добавлена в следующем обновлении")
        elif data == "admin_extend_status":
            await query.edit_message_text("🔄 Продление статуса будет добавлено в следующем обновлении")
        elif data == "back_to_admin":
            await admin_server_status(update, context)
        elif data == "confirm_upgrade":
            await handle_upgrade(update, context)
        elif data == "cancel_upgrade":
            await query.edit_message_text("❌ Улучшение статуса отменено")
    
    except Exception as e:
        logger.error(f"Ошибка в button_handler: {e}")

# ========== ЗАПУСК БОТА ==========
def main():
    """Запуск бота"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация команд
        commands = [
            # Основные команды
            ("start", start),
            ("help", help_command),
            ("balance", balance),
            ("daily", daily),
            
            # Система статусов
            ("server_status_info", server_status_info),
            ("buy_server_status", buy_server_status),
            ("payment_details", payment_details),
            ("upgrade_status", upgrade_status),
            ("admin_server_status", admin_server_status),
            ("add_payment", add_payment),
            ("give_status", give_status_command),
            
            # Налоги
            ("my_taxes", my_taxes),
            ("pay_all_taxes", pay_all_taxes),
            
            # Сберегательные счета
            ("create_savings_account", create_savings_account),
            ("my_savings", my_savings),
            ("deposit_to_savings", deposit_to_savings),
            ("withdraw_from_savings", withdraw_from_savings),
            
            # Чеки
            ("create_check", create_check),
            ("pay_check", pay_check),
            ("my_checks", my_checks),
            
            # Команды требующие статуса
            ("buy_ticket", buy_ticket_menu),
            ("create_company", create_company),
            
            # Заглушки
            ("pay", lambda u, c: u.message.reply_text("Функция перевода будет добавлена позже")),
            ("history", lambda u, c: u.message.reply_text("Функция истории будет добавлена позже")),
            ("invest", lambda u, c: u.message.reply_text("Инвестирование требует статуса на сервере")),
        ]
        
        for command, handler in commands:
            application.add_handler(CommandHandler(command, handler))
        
        # Обработчик кнопок
        application.add_handler(CallbackQueryHandler(button_handler))
        
        print("=" * 50)
        print("🤖 БОТ СО СТАТУСАМИ ЗАПУЩЕН!")
        print(f"💰 Базовый статус: {STATUS_TYPES['basic']['price_one_time']}₽ навсегда")
        print(f"💰 Базовый статус: {STATUS_TYPES['basic']['price_monthly']}₽ в месяц")
        print(f"⭐ Премиум статус: {STATUS_TYPES['premium']['price_one_time']}₽ навсегда")
        print(f"⭐ Премиум статус: {STATUS_TYPES['premium']['price_monthly']}₽ в месяц")
        print(f"👑 Админ ID: {ADMIN_IDS}")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
