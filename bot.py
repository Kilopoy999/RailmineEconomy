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

# ========== КОНСТАНТЫ ==========
SALARY_TAX_PERCENT = 13  # Налог на зарплату 13%
MINIMUM_WAGE = 16242     # МРОТ для расчета налогов
MIN_SAVINGS_DEPOSIT = 1000  # Минимальный депозит для открытия счета
SAVINGS_INTEREST_RATE = 5.0  # Годовой процент по сберегательному счету
CHECK_EXPIRY_DAYS = 30  # Срок действия чека

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
    
    # Таблица сберегательных счетов (НОВАЯ)
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
    
    # Таблица чеков (НОВАЯ)
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
    
    # Таблица налогов (НОВАЯ)
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

def generate_ticket_number():
    """Генерация уникального номера билета"""
    while True:
        letters = ''.join(random.choices(string.ascii_uppercase, k=4))
        numbers = ''.join(random.choices(string.digits, k=12))
        ticket_number = f"TKT-{letters}-{numbers[:4]}-{numbers[4:8]}-{numbers[8:]}"
        
        cursor.execute('SELECT id FROM tickets WHERE ticket_number = ?', (ticket_number,))
        if not cursor.fetchone():
            return ticket_number

def generate_seat_number():
    """Генерация номера места"""
    row = random.randint(1, 20)
    seat = random.choice(['A', 'B', 'C', 'D', 'E', 'F'])
    return f"{row}{seat}"

def generate_account_number():
    """Генерация номера счета"""
    while True:
        number = '40817' + ''.join(random.choices(string.digits, k=11))
        cursor.execute('SELECT id FROM savings_accounts WHERE account_number = ?', (number,))
        if not cursor.fetchone():
            return number

def generate_check_number():
    """Генерация номера чека"""
    while True:
        letters = ''.join(random.choices(string.ascii_uppercase, k=4))
        numbers = ''.join(random.choices(string.digits, k=12))
        check_number = f"CHK-{letters}-{numbers[:4]}-{numbers[4:8]}-{numbers[8:]}"
        
        cursor.execute('SELECT id FROM checks WHERE check_number = ?', (check_number,))
        if not cursor.fetchone():
            return check_number

def calculate_tax(salary_amount):
    """Расчет налога на зарплату"""
    taxable_amount = max(salary_amount, MINIMUM_WAGE)
    tax_amount = int(taxable_amount * SALARY_TAX_PERCENT / 100)
    return tax_amount

def log_transaction(user_id, company_id, amount, tr_type, description):
    """Логирование транзакции"""
    cursor.execute('''
        INSERT INTO transactions (user_id, company_id, amount, type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, company_id, amount, tr_type, description))
    conn.commit()

# ========== НОВЫЕ ФУНКЦИИ: НАЛОГИ ==========
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить ежедневную зарплату с налогом"""
    user_id = update.effective_user.id
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('SELECT daily_salary, last_salary_date, balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if not result:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return
    
    salary, last_date, current_balance = result
    
    if salary <= 0:
        await update.message.reply_text("❌ У вас не установлена ежедневная зарплата")
        return
    
    if last_date == today:
        await update.message.reply_text("⚠️ Вы уже получали зарплату сегодня")
        return
    
    # Рассчитываем налог
    tax_amount = calculate_tax(salary)
    net_salary = salary - tax_amount
    
    # Выдаем зарплату (минус налог)
    new_balance = current_balance + net_salary
    cursor.execute('UPDATE users SET balance = ?, last_salary_date = ? WHERE user_id = ?',
                   (new_balance, today, user_id))
    
    # Записываем начисление зарплаты
    log_transaction(user_id, None, net_salary, 'зарплата', 'Ежедневная зарплата (после налога)')
    
    # Записываем налоговое обязательство
    current_month = datetime.now().strftime('%Y-%m')
    cursor.execute('''
        INSERT INTO taxes (user_id, tax_type, amount, period, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, 'salary_tax', tax_amount, current_month, 'pending'))
    
    conn.commit()
    
    await update.message.reply_text(
        f"🎉 **ЗАРПЛАТА ПОЛУЧЕНА!**\n\n"
        f"💰 Брутто: {format_money(salary)}\n"
        f"🧾 Налог ({SALARY_TAX_PERCENT}%): -{format_money(tax_amount)}\n"
        f"💵 Чистыми: +{format_money(net_salary)}\n"
        f"💳 Новый баланс: {format_money(new_balance)}\n\n"
        f"📅 Налог к оплате до конца месяца\n"
        f"💸 Оплатить налоги: /my_taxes"
    )

async def my_taxes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мои налоги"""
    user_id = update.effective_user.id
    
    cursor.execute('''
        SELECT tax_type, amount, period, status, paid_date
        FROM taxes 
        WHERE user_id = ? AND status != 'paid'
        ORDER BY period DESC
    ''', (user_id,))
    
    taxes = cursor.fetchall()
    
    if not taxes:
        await update.message.reply_text(
            "✅ У вас нет задолженностей по налогам!\n\n"
            "📊 История налогов: /tax_history"
        )
        return
    
    total_debt = 0
    text = "🧾 **ВАШИ НАЛОГОВЫЕ ОБЯЗАТЕЛЬСТВА**\n\n"
    
    for tax_type, amount, period, status, paid_date in taxes:
        total_debt += amount
        status_icon = "⏳" if status == 'pending' else "⚠️" if status == 'overdue' else "✅"
        
        text += f"{status_icon} **{tax_type.upper()}**\n"
        text += f"📅 Период: {period}\n"
        text += f"💰 Сумма: {format_money(amount)}\n"
        text += f"📊 Статус: {status}\n"
        
        if status == 'pending':
            text += f"💸 Оплатить: /pay_tax_{period}_{tax_type}\n"
        
        text += "\n"
    
    text += f"📈 **ОБЩАЯ ЗАДОЛЖЕННОСТЬ: {format_money(total_debt)}**\n\n"
    text += "💳 **КОМАНДЫ:**\n"
    text += "/pay_all_taxes - Оплатить все налоги\n"
    text += "/tax_history - История платежей"
    
    await update.message.reply_text(text)

async def pay_tax(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплатить налог"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /pay_tax период тип\nПример: /pay_tax 2024-01 salary_tax")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Укажите период и тип налога")
        return
    
    period = context.args[0]
    tax_type = context.args[1]
    
    # Находим налог
    cursor.execute('''
        SELECT amount, status FROM taxes 
        WHERE user_id = ? AND period = ? AND tax_type = ? AND status != 'paid'
    ''', (user_id, period, tax_type))
    
    tax = cursor.fetchone()
    
    if not tax:
        await update.message.reply_text(f"❌ Налог {tax_type} за период {period} не найден или уже оплачен")
        return
    
    amount, status = tax
    
    # Проверяем баланс
    user_balance = get_user_balance(user_id)
    
    if user_balance < amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств для оплаты налога!\n"
            f"💰 Нужно: {format_money(amount)}\n"
            f"💳 Ваш баланс: {format_money(user_balance)}"
        )
        return
    
    # Оплачиваем налог
    update_user_balance(user_id, -amount)
    
    cursor.execute('''
        UPDATE taxes 
        SET status = 'paid', paid_date = ?
        WHERE user_id = ? AND period = ? AND tax_type = ?
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id, period, tax_type))
    
    log_transaction(user_id, None, -amount, 'налог', f"Оплата налога {tax_type} за {period}")
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **НАЛОГ ОПЛАЧЕН!**\n\n"
        f"📋 Тип: {tax_type}\n"
        f"📅 Период: {period}\n"
        f"💰 Сумма: {format_money(amount)}\n"
        f"📅 Дата оплаты: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"💳 Новый баланс: {format_money(user_balance - amount)}"
    )

async def pay_all_taxes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплатить все налоги"""
    user_id = update.effective_user.id
    
    cursor.execute('''
        SELECT SUM(amount) FROM taxes 
        WHERE user_id = ? AND status != 'paid'
    ''', (user_id,))
    
    total_amount = cursor.fetchone()[0]
    
    if not total_amount or total_amount == 0:
        await update.message.reply_text("✅ У вас нет задолженностей по налогам!")
        return
    
    # Проверяем баланс
    user_balance = get_user_balance(user_id)
    
    if user_balance < total_amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств для оплаты всех налогов!\n"
            f"💰 Нужно: {format_money(total_amount)}\n"
            f"💳 Ваш баланс: {format_money(user_balance)}\n\n"
            f"💸 Оплатить по отдельности: /my_taxes"
        )
        return
    
    # Оплачиваем все налоги
    update_user_balance(user_id, -total_amount)
    
    cursor.execute('''
        UPDATE taxes 
        SET status = 'paid', paid_date = ?
        WHERE user_id = ? AND status != 'paid'
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))
    
    log_transaction(user_id, None, -total_amount, 'налог', 'Оплата всех налогов')
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **ВСЕ НАЛОГИ ОПЛАЧЕНЫ!**\n\n"
        f"💰 Общая сумма: {format_money(total_amount)}\n"
        f"📅 Дата оплаты: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"💳 Новый баланс: {format_money(user_balance - total_amount)}\n\n"
        f"📊 История платежей: /tax_history"
    )

# ========== НОВЫЕ ФУНКЦИИ: СБЕРЕГАТЕЛЬНЫЕ СЧЕТА ==========
async def create_savings_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать сберегательный счет"""
    user_id = update.effective_user.id
    
    # Проверяем, есть ли уже счет
    cursor.execute('SELECT id FROM savings_accounts WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        await update.message.reply_text(
            "❌ У вас уже есть сберегательный счет!\n"
            "💳 Посмотреть: /my_savings\n"
            "💰 Пополнить: /deposit_to_savings сумма"
        )
        return
    
    # Минимальный депозит для открытия
    min_deposit = MIN_SAVINGS_DEPOSIT
    
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    user_balance = cursor.fetchone()[0]
    
    if user_balance < min_deposit:
        await update.message.reply_text(
            f"❌ Недостаточно средств для открытия счета!\n"
            f"💰 Нужно минимум: {format_money(min_deposit)}\n"
            f"💳 Ваш баланс: {format_money(user_balance)}"
        )
        return
    
    # Создаем счет
    account_number = generate_account_number()
    
    cursor.execute('''
        INSERT INTO savings_accounts (user_id, account_number, balance, interest_rate)
        VALUES (?, ?, ?, ?)
    ''', (user_id, account_number, 0, SAVINGS_INTEREST_RATE))
    
    conn.commit()
    
    await update.message.reply_text(
        f"🏦 **СБЕРЕГАТЕЛЬНЫЙ СЧЕТ ОТКРЫТ!**\n\n"
        f"📋 **РЕКВИЗИТЫ:**\n"
        f"💳 Номер счета: `{account_number}`\n"
        f"👤 Владелец: @{update.effective_user.username}\n"
        f"📈 Процентная ставка: {SAVINGS_INTEREST_RATE}% годовых\n"
        f"💰 Минимальный депозит: {format_money(min_deposit)}\n\n"
        f"💸 **КОМАНДЫ:**\n"
        f"/deposit_to_savings сумма - Пополнить счет\n"
        f"/withdraw_from_savings сумма - Снять со счета\n"
        f"/my_savings - Мой сберегательный счет\n"
        f"/transfer_to_account номер_счета сумма - Перевод на счет"
    )

async def my_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мой сберегательный счет"""
    user_id = update.effective_user.id
    
    cursor.execute('''
        SELECT account_number, balance, interest_rate, created_date, last_interest_date
        FROM savings_accounts 
        WHERE user_id = ?
    ''', (user_id,))
    
    account = cursor.fetchone()
    
    if not account:
        await update.message.reply_text(
            "💸 У вас нет сберегательного счета!\n\n"
            "🏦 Создать счет: /create_savings_account\n"
            "💰 Минимальный депозит: {format_money(MIN_SAVINGS_DEPOSIT)}"
        )
        return
    
    account_number, balance, interest_rate, created_date, last_interest = account
    
    # Рассчитываем прогноз доходности
    yearly_interest = int(balance * interest_rate / 100)
    monthly_interest = int(yearly_interest / 12)
    daily_interest = int(yearly_interest / 365)
    
    created_date_formatted = datetime.strptime(created_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
    
    text = f"🏦 **ВАШ СБЕРЕГАТЕЛЬНЫЙ СЧЕТ**\n\n"
    text += f"💳 Номер счета: `{account_number}`\n"
    text += f"💰 Текущий баланс: {format_money(balance)}\n"
    text += f"📈 Процентная ставка: {interest_rate}% годовых\n"
    text += f"📅 Дата открытия: {created_date_formatted}\n\n"
    
    if balance > 0:
        text += f"📊 **ПРОГНОЗ ДОХОДНОСТИ:**\n"
        text += f"• В день: +{format_money(daily_interest)}\n"
        text += f"• В месяц: +{format_money(monthly_interest)}\n"
        text += f"• В год: +{format_money(yearly_interest)}\n\n"
    
    if last_interest:
        last_interest_date = datetime.strptime(last_interest, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
        text += f"📅 Последние проценты: {last_interest_date}\n\n"
    
    text += f"💸 **КОМАНДЫ:**\n"
    text += f"/deposit_to_savings сумма - Пополнить счет\n"
    text += f"/withdraw_from_savings сумма - Снять деньги\n"
    text += f"/calculate_interest сумма дней - Расчет процентов"
    
    await update.message.reply_text(text)

async def deposit_to_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пополнить сберегательный счет"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /deposit_to_savings сумма")
        return
    
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверная сумма")
        return
    
    if amount < 100:
        await update.message.reply_text("❌ Минимальная сумма пополнения: 100 ₽")
        return
    
    # Проверяем наличие счета
    cursor.execute('SELECT account_number, balance FROM savings_accounts WHERE user_id = ?', (user_id,))
    account = cursor.fetchone()
    
    if not account:
        await update.message.reply_text(
            "❌ У вас нет сберегательного счета!\n"
            "🏦 Создайте сначала: /create_savings_account"
        )
        return
    
    account_number, current_savings = account
    
    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)
    
    if user_balance < amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств на основном счете!\n"
            f"💰 Нужно: {format_money(amount)}\n"
            f"💳 Ваш баланс: {format_money(user_balance)}"
        )
        return
    
    # Переводим деньги на сберегательный счет
    update_user_balance(user_id, -amount)
    
    cursor.execute('UPDATE savings_accounts SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    
    log_transaction(user_id, None, -amount, 'перевод_на_сберегательный', f"Пополнение счета {account_number}")
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **СЧЕТ ПОПОЛНЕН!**\n\n"
        f"💳 Номер счета: {account_number}\n"
        f"💰 Сумма: +{format_money(amount)}\n"
        f"🏦 Новый баланс счета: {format_money(current_savings + amount)}\n"
        f"💳 Баланс основного счета: {format_money(user_balance - amount)}\n\n"
        f"📈 Годовой доход с этой суммы: {format_money(int(amount * SAVINGS_INTEREST_RATE / 100))}"
    )

async def withdraw_from_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Снять деньги со сберегательного счета"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /withdraw_from_savings сумма")
        return
    
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверная сумма")
        return
    
    if amount < 100:
        await update.message.reply_text("❌ Минимальная сумма снятия: 100 ₽")
        return
    
    # Проверяем наличие счета
    cursor.execute('SELECT account_number, balance FROM savings_accounts WHERE user_id = ?', (user_id,))
    account = cursor.fetchone()
    
    if not account:
        await update.message.reply_text(
            "❌ У вас нет сберегательного счета!\n"
            "🏦 Создайте сначала: /create_savings_account"
        )
        return
    
    account_number, current_savings = account
    
    if current_savings < amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств на сберегательном счете!\n"
            f"💰 Нужно: {format_money(amount)}\n"
            f"🏦 Доступно: {format_money(current_savings)}"
        )
        return
    
    # Снимаем деньги
    cursor.execute('UPDATE savings_accounts SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    
    update_user_balance(user_id, amount)
    
    log_transaction(user_id, None, amount, 'снятие_со_сберегательного', f"Снятие со счета {account_number}")
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **ДЕНЬГИ СНЯТЫ!**\n\n"
        f"💳 Счет: {account_number}\n"
        f"💰 Сумма: -{format_money(amount)}\n"
        f"🏦 Остаток на счете: {format_money(current_savings - amount)}\n"
        f"💳 Баланс основного счета: {format_money(get_user_balance(user_id))}"
    )

async def transfer_to_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевод на счет другого пользователя"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /transfer_to_account номер_счета сумма")
        return
    
    account_number = context.args[0]
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверная сумма")
        return
    
    if amount < 100:
        await update.message.reply_text("❌ Минимальная сумма перевода: 100 ₽")
        return
    
    # Проверяем наличие своего счета
    cursor.execute('SELECT balance FROM savings_accounts WHERE user_id = ?', (user_id,))
    sender_account = cursor.fetchone()
    
    if not sender_account:
        await update.message.reply_text(
            "❌ У вас нет сберегательного счета!\n"
            "🏦 Создайте сначала: /create_savings_account"
        )
        return
    
    sender_balance = sender_account[0]
    
    if sender_balance < amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств на вашем счете!\n"
            f"💰 Нужно: {format_money(amount)}\n"
            f"🏦 Доступно: {format_money(sender_balance)}"
        )
        return
    
    # Ищем счет получателя
    cursor.execute('SELECT user_id, balance FROM savings_accounts WHERE account_number = ?', (account_number,))
    receiver_account = cursor.fetchone()
    
    if not receiver_account:
        await update.message.reply_text(f"❌ Счет {account_number} не найден")
        return
    
    receiver_id, receiver_balance = receiver_account
    
    if receiver_id == user_id:
        await update.message.reply_text("❌ Нельзя переводить самому себе")
        return
    
    # Выполняем перевод
    cursor.execute('UPDATE savings_accounts SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    cursor.execute('UPDATE savings_accounts SET balance = balance + ? WHERE user_id = ?', (amount, receiver_id))
    
    # Получаем username получателя
    cursor.execute('SELECT username FROM users WHERE user_id = ?', (receiver_id,))
    receiver_username = cursor.fetchone()[0] or "Пользователь"
    
    # Логируем
    log_transaction(user_id, None, -amount, 'межсчетный_перевод', f"Перевод на счет {account_number}")
    log_transaction(receiver_id, None, amount, 'межсчетный_перевод', f"Перевод от @{update.effective_user.username}")
    
    conn.commit()
    
    # Уведомляем получателя
    try:
        await context.bot.send_message(
            receiver_id,
            f"🏦 **ВЫ ПОЛУЧИЛИ ПЕРЕВОД НА СЧЕТ**\n\n"
            f"💳 Ваш счет: {account_number}\n"
            f"👤 Отправитель: @{update.effective_user.username}\n"
            f"💰 Сумма: +{format_money(amount)}\n"
            f"🏦 Новый баланс счета: {format_money(receiver_balance + amount)}"
        )
    except:
        pass
    
    await update.message.reply_text(
        f"✅ **ПЕРЕВОД ВЫПОЛНЕН!**\n\n"
        f"💳 Счет получателя: {account_number}\n"
        f"👤 Получатель: @{receiver_username}\n"
        f"💰 Сумма: {format_money(amount)}\n"
        f"🏦 Ваш остаток на счете: {format_money(sender_balance - amount)}"
    )

# ========== НОВЫЕ ФУНКЦИИ: ЧЕКИ ==========
async def create_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать чек"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /create_check сумма описание\nПример: /create_check 5000 Обед")
        return
    
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверная сумма")
        return
    
    if amount < 10:
        await update.message.reply_text("❌ Минимальная сумма чека: 10 ₽")
        return
    
    description = ' '.join(context.args[1:])
    
    # Проверяем баланс
    user_balance = get_user_balance(user_id)
    
    if user_balance < amount:
        await update.message.reply_text(
            f"❌ Недостаточно средств для создания чека!\n"
            f"💰 Нужно: {format_money(amount)}\n"
            f"💳 Ваш баланс: {format_money(user_balance)}"
        )
        return
    
    # Резервируем средства (списываем сразу)
    update_user_balance(user_id, -amount)
    
    # Создаем чек
    check_number = generate_check_number()
    expiry_date = (datetime.now() + timedelta(days=CHECK_EXPIRY_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
        INSERT INTO checks (check_number, from_user_id, amount, description, expiry_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (check_number, user_id, amount, description, expiry_date))
    
    log_transaction(user_id, None, -amount, 'чек_выписан', f"Выписан чек {check_number}")
    
    conn.commit()
    
    expiry_date_formatted = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
    
    await update.message.reply_text(
        f"🧾 **ЧЕК ВЫПИСАН!**\n\n"
        f"📋 **ИНФОРМАЦИЯ О ЧЕКЕ:**\n"
        f"🎫 Номер чека: `{check_number}`\n"
        f"💰 Сумма: {format_money(amount)}\n"
        f"📝 Описание: {description}\n"
        f"👤 Эмитент: @{update.effective_user.username}\n"
        f"📅 Срок действия: до {expiry_date_formatted}\n"
        f"💳 Сумма зарезервирована на вашем счете\n\n"
        f"💸 **КАК ОПЛАТИТЬ ЧЕК:**\n"
        f"Получатель должен отправить:\n"
        f"`/pay_check {check_number}`\n\n"
        f"📋 **ВАШИ ЧЕКИ:** /my_checks\n"
        f"💰 **ОТМЕНИТЬ ЧЕК:** /cancel_check {check_number}"
    )

async def pay_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплатить чек"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /pay_check НОМЕР_ЧЕКА")
        return
    
    check_number = context.args[0].upper()
    
    # Находим чек
    cursor.execute('''
        SELECT c.id, c.from_user_id, c.to_user_id, c.amount, c.description, 
               c.status, c.expiry_date, u.username
        FROM checks c
        JOIN users u ON c.from_user_id = u.user_id
        WHERE c.check_number = ?
    ''', (check_number,))
    
    check = cursor.fetchone()
    
    if not check:
        await update.message.reply_text(f"❌ Чек {check_number} не найден")
        return
    
    (check_id, from_user_id, to_user_id, amount, description, 
     status, expiry_date, issuer_username) = check
    
    if status != 'pending':
        await update.message.reply_text(f"❌ Чек уже {status}")
        return
    
    if to_user_id and to_user_id != user_id:
        await update.message.reply_text("❌ Этот чек предназначен другому получателю")
        return
    
    # Проверяем срок действия
    expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expiry:
        cursor.execute('UPDATE checks SET status = "expired" WHERE id = ?', (check_id,))
        conn.commit()
        await update.message.reply_text("❌ Срок действия чека истек")
        return
    
    if from_user_id == user_id:
        await update.message.reply_text("❌ Нельзя оплатить собственный чек")
        return
    
    # Обновляем чек (назначаем получателя)
    if not to_user_id:
        cursor.execute('UPDATE checks SET to_user_id = ? WHERE id = ?', (user_id, check_id))
    
    # Переводим деньги получателю
    update_user_balance(user_id, amount)
    
    # Обновляем статус чека
    cursor.execute('''
        UPDATE checks 
        SET status = 'paid', paid_date = ?
        WHERE id = ?
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), check_id))
    
    # Логируем
    log_transaction(user_id, None, amount, 'чек_оплачен', f"Оплата чека {check_number}")
    
    conn.commit()
    
    # Уведомляем эмитента чека
    try:
        await context.bot.send_message(
            from_user_id,
            f"🧾 **ВАШ ЧЕК ОПЛАЧЕН!**\n\n"
            f"🎫 Номер чека: {check_number}\n"
            f"💰 Сумма: {format_money(amount)}\n"
            f"📝 Описание: {description}\n"
            f"👤 Получатель: @{update.effective_user.username}\n"
            f"📅 Дата оплаты: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
    except:
        pass
    
    await update.message.reply_text(
        f"✅ **ЧЕК ОПЛАЧЕН!**\n\n"
        f"🎫 Номер чека: {check_number}\n"
        f"💰 Сумма: +{format_money(amount)}\n"
        f"📝 Описание: {description}\n"
        f"👤 Эмитент: @{issuer_username}\n"
        f"💳 Ваш баланс: {format_money(get_user_balance(user_id))}\n\n"
        f"📋 Ваши чеки: /my_checks"
    )

async def my_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мои чеки"""
    user_id = update.effective_user.id
    
    # Чеки, которые я выписал
    cursor.execute('''
        SELECT check_number, amount, description, status, expiry_date, 
               to_user_id, u.username, paid_date
        FROM checks c
        LEFT JOIN users u ON c.to_user_id = u.user_id
        WHERE from_user_id = ?
        ORDER BY created_date DESC
        LIMIT 20
    ''', (user_id,))
    
    issued_checks = cursor.fetchall()
    
    # Чеки, которые я оплатил
    cursor.execute('''
        SELECT check_number, amount, description, status, expiry_date,
               u.username as issuer_username, paid_date
        FROM checks c
        JOIN users u ON c.from_user_id = u.user_id
        WHERE to_user_id = ?
        ORDER BY paid_date DESC
        LIMIT 20
    ''', (user_id,))
    
    received_checks = cursor.fetchall()
    
    text = "🧾 **ВАШИ ЧЕКИ**\n\n"
    
    if issued_checks:
        text += f"📤 **ВЫПИСАННЫЕ ВАМИ** ({len(issued_checks)}):\n"
        total_issued = 0
        pending_issued = 0
        
        for (check_num, amount, desc, status, expiry, 
             to_user_id, to_username, paid_date) in issued_checks[:5]:  # Показываем первые 5
            
            status_icon = "⏳" if status == 'pending' else "✅" if status == 'paid' else "❌"
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S').strftime('%d.%m') if expiry else "—"
            
            text += f"{status_icon} `{check_num}`\n"
            text += f"   💰 {format_money(amount)} | 📝 {desc[:20]}...\n"
            
            if status == 'pending':
                text += f"   📅 Истекает: {expiry_date}\n"
                pending_issued += amount
            elif status == 'paid' and to_username:
                text += f"   👤 Оплатил: @{to_username}\n"
            
            total_issued += amount
            text += "\n"
        
        if len(issued_checks) > 5:
            text += f"... и еще {len(issued_checks) - 5} чеков\n"
        
        text += f"📊 Всего выписано: {format_money(total_issued)}\n"
        text += f"⏳ Ожидает оплаты: {format_money(pending_issued)}\n\n"
    
    if received_checks:
        text += f"📥 **ОПЛАЧЕННЫЕ ВАМИ** ({len(received_checks)}):\n"
        total_received = 0
        
        for (check_num, amount, desc, status, expiry, issuer_username, paid_date) in received_checks[:3]:
            if paid_date:
                paid = datetime.strptime(paid_date, '%Y-%m-%d %H:%M:%S').strftime('%d.%m')
            else:
                paid = "—"
            
            text += f"✅ `{check_num}`\n"
            text += f"   💰 {format_money(amount)} | 📝 {desc[:20]}...\n"
            text += f"   👤 От: @{issuer_username} | 📅 {paid}\n\n"
            
            total_received += amount
        
        if len(received_checks) > 3:
            text += f"... и еще {len(received_checks) - 3} чеков\n"
        
        text += f"📊 Всего получено: {format_money(total_received)}\n\n"
    
    if not issued_checks and not received_checks:
        text += "📭 У вас нет чеков\n"
        text += "💸 Выписать чек: /create_check сумма описание\n"
        text += "💰 Оплатить чек: /pay_check НОМЕР_ЧЕКА"
    else:
        text += "💸 **КОМАНДЫ:**\n"
        text += "/create_check сумма описание - Выписать чек\n"
        text += "/pay_check НОМЕР - Оплатить чек\n"
        text += "/check_info НОМЕР - Информация о чеке"
    
    await update.message.reply_text(text)

async def check_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о чеке"""
    if not context.args:
        await update.message.reply_text("❌ Использование: /check_info НОМЕР_ЧЕКА")
        return
    
    check_number = context.args[0].upper()
    
    cursor.execute('''
        SELECT c.check_number, c.amount, c.description, c.status, 
               c.created_date, c.expiry_date, c.paid_date,
               u1.username as issuer_username,
               u2.username as receiver_username
        FROM checks c
        JOIN users u1 ON c.from_user_id = u1.user_id
        LEFT JOIN users u2 ON c.to_user_id = u2.user_id
        WHERE c.check_number = ?
    ''', (check_number,))
    
    check = cursor.fetchone()
    
    if not check:
        await update.message.reply_text(f"❌ Чек {check_number} не найден")
        return
    
    (check_num, amount, desc, status, created, expiry, paid, 
     issuer_username, receiver_username) = check
    
    # Статус и иконка
    status_icons = {
        'pending': '⏳',
        'paid': '✅',
        'cancelled': '❌',
        'expired': '⌛'
    }
    status_icon = status_icons.get(status, '❓')
    
    created_date = datetime.strptime(created, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
    
    text = f"{status_icon} **ИНФОРМАЦИЯ О ЧЕКЕ**\n\n"
    text += f"🎫 Номер: `{check_num}`\n"
    text += f"💰 Сумма: {format_money(amount)}\n"
    text += f"📝 Описание: {desc}\n"
    text += f"👤 Эмитент: @{issuer_username}\n"
    text += f"📅 Дата создания: {created_date}\n"
    text += f"📊 Статус: {status}\n"
    
    if expiry:
        expiry_date = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
        text += f"📆 Срок действия: {expiry_date}\n"
    
    if receiver_username:
        text += f"👤 Получатель: @{receiver_username}\n"
    
    if paid:
        paid_date = datetime.strptime(paid, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
        text += f"💰 Дата оплаты: {paid_date}\n"
    
    text += "\n"
    
    if status == 'pending':
        text += "💸 **ДЕЙСТВИЯ:**\n"
        text += f"`/pay_check {check_num}` - Оплатить чек\n"
        
        user_id = update.effective_user.id
        cursor.execute('SELECT from_user_id FROM checks WHERE check_number = ?', (check_num,))
        issuer_id = cursor.fetchone()[0]
        
        if user_id == issuer_id:
            text += f"`/cancel_check {check_num}` - Отменить чек\n"
    
    await update.message.reply_text(text)

async def cancel_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменить чек"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Использование: /cancel_check НОМЕР_ЧЕКА")
        return
    
    check_number = context.args[0].upper()
    
    # Находим чек
    cursor.execute('SELECT id, from_user_id, amount, status FROM checks WHERE check_number = ?', (check_number,))
    check = cursor.fetchone()
    
    if not check:
        await update.message.reply_text(f"❌ Чек {check_number} не найден")
        return
    
    check_id, from_user_id, amount, status = check
    
    if from_user_id != user_id:
        await update.message.reply_text("❌ Вы не являетесь эмитентом этого чека")
        return
    
    if status != 'pending':
        await update.message.reply_text(f"❌ Невозможно отменить чек со статусом '{status}'")
        return
    
    # Отменяем чек и возвращаем деньги
    cursor.execute('UPDATE checks SET status = "cancelled" WHERE id = ?', (check_id,))
    
    update_user_balance(user_id, amount)  # Возвращаем деньги
    
    log_transaction(user_id, None, amount, 'чек_отменен', f"Отмена чека {check_number}")
    
    conn.commit()
    
    await update.message.reply_text(
        f"✅ **ЧЕК ОТМЕНЕН!**\n\n"
        f"🎫 Номер чека: {check_number}\n"
        f"💰 Возвращено: {format_money(amount)}\n"
        f"💳 Ваш баланс: {format_money(get_user_balance(user_id))}"
    )

# ========== БАЗОВЫЕ КОМАНДЫ (уже существующие) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)',
                      (user_id, user.username, user.full_name))
        conn.commit()
        
        welcome_text = (
            f"👋 Привет, {user.full_name}!\n\n"
            f"🏦 **ЭКОНОМИЧЕСКАЯ СИСТЕМА С НОВЫМИ ФУНКЦИЯМИ**\n\n"
            f"💰 **НОВИНКИ:**\n"
            f"• 🧾 Налог на зарплату 13%\n"
            f"• 🏦 Сберегательные счета с 5%\n"
            f"• 🎫 Чеки для расчетов\n\n"
            f"📋 **ОСНОВНЫЕ РАЗДЕЛЫ:**\n"
            f"💰 Финансы: /balance, /pay, /daily\n"
            f"🧾 Налоги: /my_taxes, /pay_all_taxes\n"
            f"🏦 Счета: /create_savings_account, /my_savings\n"
            f"🎫 Чеки: /create_check, /my_checks\n"
            f"🏢 Компании: /create_company\n"
            f"🚂 Билеты: /buy_ticket\n\n"
            f"📚 Подробнее: /help"
        )
        
        await update.message.reply_text(welcome_text)
    else:
        await update.message.reply_text(f"С возвращением, {user.full_name}!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь по командам"""
    user_id = update.effective_user.id
    
    if is_admin(user_id):
        help_text = (
            "👑 **АДМИН КОМАНДЫ:**\n"
            "/add @user сумма причина - Выдать деньги\n"
            "/remove @user сумма причина - Списать\n"
            "/stats - Статистика\n\n"
            
            "💰 **ФИНАНСЫ:**\n"
            "/balance - Баланс\n"
            "/daily - Зарплата (с налогом 13%)\n"
            "/pay @user сумма - Перевод\n"
            "/history - История операций\n\n"
            
            "🧾 **НАЛОГИ:**\n"
            "/my_taxes - Мои налоги\n"
            "/pay_all_taxes - Оплатить все\n"
            "/tax_history - История платежей\n\n"
            
            "🏦 **СБЕРЕГАТЕЛЬНЫЕ СЧЕТА:**\n"
            "/create_savings_account - Открыть счет\n"
            "/my_savings - Мой счет\n"
            "/deposit_to_savings сумма - Пополнить\n"
            "/withdraw_from_savings сумма - Снять\n"
            "/transfer_to_account номер сумма - Перевод\n\n"
            
            "🎫 **ЧЕКИ:**\n"
            "/create_check сумма описание - Выписать\n"
            "/pay_check НОМЕР - Оплатить чек\n"
            "/my_checks - Мои чеки\n"
            "/check_info НОМЕР - Инфо о чеке\n"
            "/cancel_check НОМЕР - Отменить\n\n"
            
            "🏢 **КОМПАНИИ:**\n"
            "/create_company Название TAG\n"
            "/my_companies - Мои компании\n"
            "/company_info #TAG - Инфо\n\n"
            
            "🚂 **БИЛЕТЫ:**\n"
            "/buy_ticket - Купить билет\n"
            "/my_tickets - Мои билеты"
        )
    else:
        help_text = (
            "👤 **ОСНОВНЫЕ КОМАНДЫ:**\n"
            "/start - Регистрация\n"
            "/balance - Баланс\n"
            "/daily - Зарплата (налог 13%)\n"
            "/pay @user сумма - Перевод\n"
            "/history - История\n\n"
            
            "🧾 **НАЛОГИ:**\n"
            "/my_taxes - Мои налоги\n"
            "/pay_all_taxes - Оплатить все\n\n"
            
            "🏦 **СБЕРЕГАТЕЛЬНЫЕ СЧЕТА:**\n"
            "/create_savings_account - Открыть счет\n"
            "/my_savings - Мой счет\n"
            "/deposit_to_savings сумма - Пополнить\n"
            "/withdraw_from_savings сумма - Снять\n\n"
            
            "🎫 **ЧЕКИ:**\n"
            "/create_check сумма описание - Выписать\n"
            "/pay_check НОМЕР - Оплатить чек\n"
            "/my_checks - Мои чеки\n\n"
            
            "🏢 **КОМПАНИИ:**\n"
            "/create_company Название TAG\n"
            "/my_companies - Мои компании\n\n"
            
            "🚂 **БИЛЕТЫ:**\n"
            "/buy_ticket - Купить билет\n"
            "/my_tickets - Мои билеты\n\n"
            
            "/help - Эта справка"
        )
    
    await update.message.reply_text(help_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    cursor.execute('SELECT balance, daily_salary FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        balance_amount, salary = result
        
        # Проверяем сберегательный счет
        cursor.execute('SELECT balance FROM savings_accounts WHERE user_id = ?', (user_id,))
        savings = cursor.fetchone()
        savings_balance = savings[0] if savings else 0
        
        # Проверяем налоги
        cursor.execute('SELECT SUM(amount) FROM taxes WHERE user_id = ? AND status != "paid"', (user_id,))
        taxes = cursor.fetchone()[0] or 0
        
        # Проверяем активные чеки
        cursor.execute('SELECT SUM(amount) FROM checks WHERE from_user_id = ? AND status = "pending"', (user_id,))
        pending_checks = cursor.fetchone()[0] or 0
        
        text = f"💳 **ВАШИ ФИНАНСЫ**\n\n"
        text += f"💰 Основной счет: {format_money(balance_amount)}\n"
        
        if savings_balance > 0:
            text += f"🏦 Сберегательный счет: {format_money(savings_balance)}\n"
        
        text += f"📈 Общий капитал: {format_money(balance_amount + savings_balance)}\n\n"
        
        if salary > 0:
            tax = calculate_tax(salary)
            net_salary = salary - tax
            text += f"🎯 Зарплата: {format_money(salary)}/день\n"
            text += f"🧾 Чистыми: {format_money(net_salary)} (налог {format_money(tax)})\n\n"
        
        if taxes > 0:
            text += f"⚠️ Задолженность по налогам: {format_money(taxes)}\n"
        
        if pending_checks > 0:
            text += f"🧾 Зарезервировано в чеках: {format_money(pending_checks)}\n"
        
        text += f"\n💸 **БЫСТРЫЕ КОМАНДЫ:**\n"
        text += f"/my_savings - Сберегательный счет\n"
        text += f"/my_taxes - Налоги\n"
        text += f"/my_checks - Чеки"
        
        await update.message.reply_text(text)
    else:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")

# ========== ЗАПУСК БОТА ==========
def main():
    """Запуск бота"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация команд
        commands = [
            # Базовые команды
            ("start", start),
            ("help", help_command),
            ("balance", balance),
            ("daily", daily),
            
            # Налоги
            ("my_taxes", my_taxes),
            ("pay_tax", pay_tax),
            ("pay_all_taxes", pay_all_taxes),
            
            # Сберегательные счета
            ("create_savings_account", create_savings_account),
            ("my_savings", my_savings),
            ("deposit_to_savings", deposit_to_savings),
            ("withdraw_from_savings", withdraw_from_savings),
            ("transfer_to_account", transfer_to_account),
            
            # Чеки
            ("create_check", create_check),
            ("pay_check", pay_check),
            ("my_checks", my_checks),
            ("check_info", check_info),
            ("cancel_check", cancel_check),
            
            # Команды которые нужно добавить позже (заглушки)
            ("pay", lambda u, c: u.message.reply_text("Функция перевода будет добавлена позже")),
            ("history", lambda u, c: u.message.reply_text("Функция истории будет добавлена позже")),
            ("add", lambda u, c: u.message.reply_text("Админ команда будет добавлена позже")),
            ("stats", lambda u, c: u.message.reply_text("Статистика будет добавлена позже")),
            ("create_company", lambda u, c: u.message.reply_text("Создание компании будет добавлено позже")),
            ("buy_ticket", lambda u, c: u.message.reply_text("Покупка билетов будет добавлена позже")),
        ]
        
        for command, handler in commands:
            application.add_handler(CommandHandler(command, handler))
        
        print("=" * 50)
        print("🤖 БОТ С НОВЫМИ ФУНКЦИЯМИ ЗАПУСКАЕТСЯ...")
        print(f"💰 Налог на зарплату: {SALARY_TAX_PERCENT}%")
        print(f"🏦 Процент по вкладам: {SAVINGS_INTEREST_RATE}%")
        print(f"🧾 Срок действия чеков: {CHECK_EXPIRY_DAYS} дней")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
