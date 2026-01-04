import subprocess
import sys

# Автоматическая установка зависимостей
def install_dependencies():
    """Установка необходимых пакетов, если они отсутствуют"""
    required_packages = [
        ('aiogram', 'aiogram==3.0.0b7'),
        ('dateutil', 'python-dateutil==2.8.2')
    ]
    
    for package_name, package_spec in required_packages:
        try:
            __import__(package_name)
            print(f"✓ {package_name} уже установлен")
        except ImportError:
            print(f"📦 Установка {package_name}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec])
                print(f"✓ {package_name} успешно установлен")
            except subprocess.CalledProcessError as e:
                print(f"✗ Ошибка установки {package_name}: {e}")
                # Пробуем установить без версии
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                except:
                    print(f"✗ Критическая ошибка: не удалось установить {package_name}")
                    sys.exit(1)

# Устанавливаем зависимости
install_dependencies()

# Теперь импортируем остальные модули
import asyncio
import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации из переменных окружения или использование значений по умолчанию
def load_config():
    """Загрузка конфигурации"""
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8498581637:AAF4Z59SYbdP9Z2Jk6oM3EnJ0tsXAbQvPDw")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "6339108316"))
    
    # Проверка токена
    if not BOT_TOKEN or BOT_TOKEN == "ваш_токен_здесь":
        logger.error("❌ Токен бота не установлен! Укажите BOT_TOKEN в переменных окружения.")
        sys.exit(1)
    
    return BOT_TOKEN, ADMIN_ID

BOT_TOKEN, ADMIN_ID = load_config()

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
def init_db():
    """Инициализация базы данных SQLite"""
    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        # Таблица пользователей и баланса
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            balance REAL DEFAULT 1000.0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица компаний/бизнесов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            company_name TEXT,
            company_type TEXT,
            description TEXT,
            capital REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(user_id)
        )
        ''')
        
        # Таблица сотрудников компаний
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS company_employees (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            user_id INTEGER,
            position TEXT,
            salary REAL DEFAULT 0.0,
            FOREIGN KEY (company_id) REFERENCES companies(company_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')
        
        # Таблица железнодорожных маршрутов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS train_routes (
            route_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            route_number TEXT,
            route_name TEXT,
            direction TEXT,
            departure_time TIMESTAMP,
            price REAL DEFAULT 100.0,
            seats INTEGER DEFAULT 50,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
        ''')
        
        # Таблица билетов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER,
            buyer_id INTEGER,
            seat_number TEXT,
            price REAL,
            purchase_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (route_id) REFERENCES train_routes(route_id),
            FOREIGN KEY (buyer_id) REFERENCES users(user_id)
        )
        ''')
        
        # Таблица чеков
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS checks (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            amount REAL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            claimed INTEGER DEFAULT 0,
            claimed_by INTEGER,
            claimed_at TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(user_id),
            FOREIGN KEY (claimed_by) REFERENCES users(user_id)
        )
        ''')
        
        # Таблица транзакций
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            amount REAL,
            description TEXT,
            transaction_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица логов действий
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS action_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except sqlite3.Error as e:
        logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        raise

# Классы состояний для FSM
class CompanyCreation(StatesGroup):
    name = State()
    type = State()
    description = State()

class TrainRouteCreation(StatesGroup):
    number = State()
    name = State()
    direction = State()
    departure_date = State()
    price = State()

class MoneyTransfer(StatesGroup):
    amount = State()
    recipient_id = State()
    description = State()

class CheckCreation(StatesGroup):
    amount = State()
    description = State()

class AdminAddBalance(StatesGroup):
    user_id = State()
    amount = State()

# Вспомогательные функции
def get_db_connection():
    """Создание соединения с базой данных"""
    return sqlite3.connect('bot_database.db')

def ensure_user_exists(user_id: int, username: str = None, full_name: str = None):
    """Создает запись о пользователе, если её нет"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
        INSERT INTO users (user_id, username, full_name, balance) 
        VALUES (?, ?, ?, ?)
        ''', (user_id, username, full_name, 1000.0))
        conn.commit()
        logger.info(f"✅ Создан новый пользователь: {user_id} ({full_name})")
    
    conn.close()

def log_action(user_id: int, action: str, details: str = ""):
    """Логирование действий пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO action_logs (user_id, action, details) 
    VALUES (?, ?, ?)
    ''', (user_id, action, details))
    
    conn.commit()
    conn.close()

# ==================== КОМАНДЫ АДМИНИСТРАТОРА ====================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    """Панель администратора"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Добавить баланс", callback_data="admin_add_balance"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="🏢 Управление компаниями", callback_data="admin_companies"),
            InlineKeyboardButton(text="🚆 Управление маршрутами", callback_data="admin_routes")
        ],
        [
            InlineKeyboardButton(text="📈 Топ пользователей", callback_data="admin_top_users"),
            InlineKeyboardButton(text="📋 Логи действий", callback_data="admin_logs")
        ],
        [
            InlineKeyboardButton(text="🔄 Сброс данных", callback_data="admin_reset"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
        ]
    ])
    
    await message.answer("👑 **Панель администратора**", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    """Статистика системы"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем статистику
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM companies')
    company_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM train_routes')
    route_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tickets')
    ticket_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(amount) FROM checks WHERE claimed = 1')
    checks_claimed = cursor.fetchone()[0] or 0
    
    # Активные маршруты
    cursor.execute('SELECT COUNT(*) FROM train_routes WHERE departure_time > datetime("now")')
    active_routes = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""
📊 **Статистика системы:**

👥 **Пользователи:**
• Всего пользователей: {user_count}
• Общий баланс: {total_balance:.2f}

🏢 **Бизнес:**
• Компаний: {company_count}
• Всего капитала: {cursor.execute('SELECT SUM(capital) FROM companies').fetchone()[0] or 0:.2f}

🚆 **Транспорт:**
• Маршрутов: {route_count}
• Активных маршрутов: {active_routes}
• Проданных билетов: {ticket_count}

💰 **Финансы:**
• Оплачено чеков: {checks_claimed:.2f}
• Всего транзакций: {cursor.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]}
    """
    
    await callback.message.edit_text(stats_text)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления баланса"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет прав!")
        return
    
    await callback.message.answer("👤 Введите ID пользователя для пополнения баланса:")
    await state.set_state(AdminAddBalance.user_id)
    await callback.answer()

@dp.message(AdminAddBalance.user_id)
async def admin_add_balance_user(message: Message, state: FSMContext):
    """Обработка ID пользователя"""
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("💰 Введите сумму для пополнения:")
        await state.set_state(AdminAddBalance.amount)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")

@dp.message(AdminAddBalance.amount)
async def admin_add_balance_amount(message: Message, state: FSMContext):
    """Завершение пополнения баланса"""
    try:
        amount = float(message.text)
        data = await state.get_data()
        user_id = data['user_id']
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        
        # Обновляем баланс
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем существование пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            # Создаем пользователя если не существует
            cursor.execute('INSERT INTO users (user_id, balance) VALUES (?, ?)', (user_id, amount))
            result_text = f"✅ Создан новый пользователь {user_id} с балансом {amount:.2f}"
        else:
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            new_balance = cursor.fetchone()[0]
            result_text = f"✅ Баланс пользователя {user_id} пополнен на {amount:.2f}\nНовый баланс: {new_balance:.2f}"
        
        # Логируем транзакцию
        cursor.execute('''
        INSERT INTO transactions (sender_id, receiver_id, amount, description) 
        VALUES (?, ?, ?, ?)
        ''', (ADMIN_ID, user_id, amount, "Административное пополнение"))
        
        # Логируем действие
        log_action(message.from_user.id, "admin_add_balance", f"user_id={user_id}, amount={amount}")
        
        conn.commit()
        conn.close()
        
        await message.answer(result_text)
        
        # Уведомляем пользователя
        try:
            await bot.send_message(user_id, f"💰 Ваш баланс пополнен администратором на {amount:.2f}")
        except:
            pass
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число:")
    finally:
        await state.clear()

@dp.callback_query(F.data == "admin_top_users")
async def admin_top_users(callback: CallbackQuery):
    """Топ пользователей по балансу"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT user_id, username, full_name, balance 
    FROM users 
    ORDER BY balance DESC 
    LIMIT 10
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    text = "🏆 **Топ-10 пользователей по балансу:**\n\n"
    
    for i, user in enumerate(users, 1):
        user_id, username, full_name, balance = user
        name = full_name or username or f"ID: {user_id}"
        text += f"{i}. {name} - {balance:.2f}\n"
    
    await callback.message.edit_text(text)
    await callback.answer()

# ==================== КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ====================
@dp.message(Command("start"))
async def start_command(message: Message):
    """Команда /start"""
    ensure_user_exists(message.from_user.id, message.from_user.username, message.from_user.full_name)
    log_action(message.from_user.id, "start_command")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="💸 Перевести", callback_data="transfer_menu")],
        [InlineKeyboardButton(text="🏢 Мои компании", callback_data="my_companies")],
        [InlineKeyboardButton(text="🎫 Билеты", callback_data="my_tickets")],
        [InlineKeyboardButton(text="🧾 Чеки", callback_data="checks_menu")],
        [InlineKeyboardButton(text="🚆 Маршруты", callback_data="routes_menu")]
    ])
    
    welcome_text = f"""
👋 Привет, {message.from_user.full_name or message.from_user.username}!

🤖 **Я - экономический Telegram бот** с полным набором функций:

💸 **Финансы:**
• Проверка баланса и история транзакций
• Переводы между пользователями
• Выписка и оплата чеков

🏢 **Бизнес:**
• Создание компаний разных типов
• Управление капиталом компании
• Нанять сотрудников (в разработке)

🚆 **Транспорт:**
• Создание ЖД маршрутов (для владельцев ЖД компаний)
• Покупка билетов на поезда
• Просмотр активных маршрутов

📱 **Используйте кнопки ниже или команды:**
/balance - ваш баланс
/transfer - перевод денег
/create_company - создать компанию
/buy_ticket - купить билет
/create_check - создать чек
/create_route - создать маршрут
/help - список всех команд
    """
    
    await message.answer(welcome_text, reply_markup=keyboard)

@dp.message(Command("help"))
async def help_command(message: Message):
    """Справка по командам"""
    help_text = """
🤖 **ДОСТУПНЫЕ КОМАНДЫ:**

💰 **ФИНАНСЫ:**
/balance - ваш баланс
/transfer - перевод денег
/transactions - история транзакций
/create_check - создать чек
/pay_check [ID] - оплатить чек
/checks - список доступных чеков

🏢 **БИЗНЕС:**
/create_company - создать компанию
/my_companies - мои компании
/company_info [ID] - информация о компании

🚆 **ТРАНСПОРТ:**
/create_route - создать маршрут (для ЖД компаний)
/buy_ticket - купить билет
/my_tickets - мои билеты
/routes - доступные маршруты

👑 **АДМИН:** (только администратор)
/admin - панель администратора

📱 **БЫСТРЫЙ ДОСТУП:**
Используйте кнопки меню под сообщениями!
    """
    
    await message.answer(help_text)
    log_action(message.from_user.id, "help_command")

@dp.message(Command("balance"))
async def balance_command(message: Message):
    """Показать баланс"""
    ensure_user_exists(message.from_user.id)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,))
    balance = cursor.fetchone()[0]
    
    # Получаем последние транзакции
    cursor.execute('''
    SELECT * FROM transactions 
    WHERE sender_id = ? OR receiver_id = ? 
    ORDER BY transaction_time DESC 
    LIMIT 5
    ''', (message.from_user.id, message.from_user.id))
    
    transactions = cursor.fetchall()
    conn.close()
    
    text = f"💰 **Ваш баланс:** {balance:.2f}\n\n"
    
    if transactions:
        text += "📋 **Последние транзакции:**\n"
        for trans in transactions:
            _, sender, receiver, amount, desc, time = trans
            time_str = datetime.strptime(time, "%Y-%m-%d %H:%M:%S").strftime("%d.%m %H:%M")
            
            if sender == message.from_user.id:
                text += f"➖ {time_str}: -{amount:.2f} → {receiver} ({desc})\n"
            else:
                text += f"➕ {time_str}: +{amount:.2f} ← {sender} ({desc})\n"
    
    await message.answer(text)
    log_action(message.from_user.id, "balance_check")

@dp.callback_query(F.data == "balance")
async def balance_callback(callback: CallbackQuery):
    """Показать баланс (callback)"""
    await balance_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "transfer_menu")
async def transfer_menu(callback: CallbackQuery, state: FSMContext):
    """Меню перевода денег"""
    await callback.message.answer("💸 Введите сумму для перевода:")
    await state.set_state(MoneyTransfer.amount)
    await callback.answer()

@dp.message(Command("transfer"))
async def transfer_command(message: Message, state: FSMContext):
    """Начать перевод денег"""
    await message.answer("💸 Введите сумму для перевода:")
    await state.set_state(MoneyTransfer.amount)

@dp.message(MoneyTransfer.amount)
async def process_transfer_amount(message: Message, state: FSMContext):
    """Обработка суммы перевода"""
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        
        # Проверяем баланс
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,))
        balance = cursor.fetchone()[0]
        conn.close()
        
        if balance < amount:
            await message.answer(f"❌ Недостаточно средств. Ваш баланс: {balance:.2f}")
            await state.clear()
            return
        
        await state.update_data(amount=amount)
        await message.answer("👤 Введите ID получателя:")
        await state.set_state(MoneyTransfer.recipient_id)
    except ValueError:
        await message.answer("❌ Введите корректную сумму (число)")

@dp.message(MoneyTransfer.recipient_id)
async def process_transfer_recipient(message: Message, state: FSMContext):
    """Обработка ID получателя"""
    try:
        recipient_id = int(message.text)
        
        if recipient_id == message.from_user.id:
            await message.answer("❌ Нельзя переводить самому себе")
            await state.clear()
            return
        
        await state.update_data(recipient_id=recipient_id)
        await message.answer("📝 Введите описание перевода (не обязательно):")
        await state.set_state(MoneyTransfer.description)
    except ValueError:
        await message.answer("❌ Введите корректный ID (число)")

@dp.message(MoneyTransfer.description)
async def process_transfer_description(message: Message, state: FSMContext):
    """Завершение перевода"""
    data = await state.get_data()
    amount = data['amount']
    recipient_id = data['recipient_id']
    description = message.text
    
    sender_id = message.from_user.id
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование получателя
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (recipient_id,))
    recipient = cursor.fetchone()
    
    if not recipient:
        await message.answer("❌ Получатель не найден")
        conn.close()
        await state.clear()
        return
    
    # Проверяем баланс отправителя еще раз
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (sender_id,))
    sender_balance = cursor.fetchone()[0]
    
    if sender_balance < amount:
        await message.answer("❌ Недостаточно средств")
        conn.close()
        await state.clear()
        return
    
    # Выполняем перевод
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, sender_id))
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, recipient_id))
    
    # Логируем транзакцию
    cursor.execute('''
    INSERT INTO transactions (sender_id, receiver_id, amount, description) 
    VALUES (?, ?, ?, ?)
    ''', (sender_id, recipient_id, amount, description))
    
    # Логируем действие
    log_action(sender_id, "money_transfer", f"to={recipient_id}, amount={amount}")
    
    conn.commit()
    conn.close()
    
    # Уведомляем отправителя
    await message.answer(f"""
✅ Перевод выполнен!

Сумма: {amount:.2f}
Получатель: {recipient_id}
Описание: {description}

Ваш текущий баланс: {sender_balance - amount:.2f}
    """)
    
    # Уведомляем получателя
    try:
        await bot.send_message(
            recipient_id,
            f"""
💰 Вы получили перевод!

Сумма: +{amount:.2f}
Отправитель: {sender_id}
Описание: {description}
            """
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить получателя {recipient_id}: {e}")
    
    await state.clear()

@dp.message(Command("create_company"))
async def create_company_command(message: Message, state: FSMContext):
    """Создание компании"""
    await message.answer("🏢 Введите название компании:")
    await state.set_state(CompanyCreation.name)

@dp.message(CompanyCreation.name)
async def process_company_name(message: Message, state: FSMContext):
    """Обработка названия компании"""
    company_name = message.text.strip()
    
    if len(company_name) < 3:
        await message.answer("❌ Название должно содержать минимум 3 символа")
        return
    
    await state.update_data(name=company_name)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚆 Железная дорога", callback_data="type_railway")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="type_bank")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="type_shop")],
        [InlineKeyboardButton(text="🏭 Завод", callback_data="type_factory")],
        [InlineKeyboardButton(text="🏨 Отель", callback_data="type_hotel")],
        [InlineKeyboardButton(text="📦 Транспорт", callback_data="type_transport")]
    ])
    
    await message.answer("📊 Выберите тип компании:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("type_"))
async def process_company_type_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа компании"""
    type_map = {
        "type_railway": "Железная дорога",
        "type_bank": "Банк",
        "type_shop": "Магазин",
        "type_factory": "Завод",
        "type_hotel": "Отель",
        "type_transport": "Транспортная компания"
    }
    
    company_type = type_map.get(callback.data, "Другое")
    await state.update_data(type=company_type)
    
    await callback.message.answer("📝 Введите описание компании:")
    await state.set_state(CompanyCreation.description)
    await callback.answer()

@dp.message(CompanyCreation.type)
async def process_company_type(message: Message, state: FSMContext):
    """Обработка типа компании (текстовый ввод)"""
    await state.update_data(type=message.text)
    await message.answer("📝 Введите описание компании:")
    await state.set_state(CompanyCreation.description)

@dp.message(CompanyCreation.description)
async def process_company_description(message: Message, state: FSMContext):
    """Завершение создания компании"""
    data = await state.get_data()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем, не существует ли компания с таким названием
    cursor.execute('SELECT * FROM companies WHERE company_name = ?', (data['name'],))
    existing = cursor.fetchone()
    
    if existing:
        await message.answer("❌ Компания с таким названием уже существует")
        conn.close()
        await state.clear()
        return
    
    # Создаем компанию
    cursor.execute('''
    INSERT INTO companies (owner_id, company_name, company_type, description) 
    VALUES (?, ?, ?, ?)
    ''', (message.from_user.id, data['name'], data['type'], message.text))
    
    company_id = cursor.lastrowid
    
    # Логируем действие
    log_action(message.from_user.id, "company_create", f"name={data['name']}, type={data['type']}")
    
    conn.commit()
    conn.close()
    
    await message.answer(f"""
✅ Компания создана!

ID компании: {company_id}
Название: {data['name']}
Тип: {data['type']}
Описание: {message.text}

💡 Владельцы ЖД компаний могут создавать маршруты командой /create_route
    """)
    
    await state.clear()

@dp.callback_query(F.data == "my_companies")
async def my_companies_callback(callback: CallbackQuery):
    """Показать компании пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT company_id, company_name, company_type, description, capital 
    FROM companies WHERE owner_id = ?
    ORDER BY created_at DESC
    ''', (callback.from_user.id,))
    
    companies = cursor.fetchall()
    conn.close()
    
    if not companies:
        await callback.message.answer("🏢 У вас пока нет компаний")
        await callback.answer()
        return
    
    text = "🏢 **Ваши компании:**\n\n"
    
    for company in companies:
        company_id, name, ctype, desc, capital = company
        text += f"🏢 **{name}** (ID: {company_id})\n"
        text += f"Тип: {ctype}\n"
        text += f"Капитал: {capital:.2f}\n"
        if desc:
            text += f"Описание: {desc}\n"
        text += "─" * 30 + "\n"
    
    await callback.message.answer(text)
    await callback.answer()

@dp.message(Command("create_route"))
async def create_route_command(message: Message, state: FSMContext):
    """Создание железнодорожного маршрута"""
    # Проверяем, есть ли у пользователя ЖД компания
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT company_id, company_name FROM companies 
    WHERE owner_id = ? AND (company_type LIKE '%ЖД%' OR company_type LIKE '%железнодорож%' OR company_type = 'Железная дорога')
    ''', (message.from_user.id,))
    
    company = cursor.fetchone()
    conn.close()
    
    if not company:
        await message.answer("""
❌ Создавать маршруты могут только владельцы ЖД компаний!

Сначала создайте компанию типа "Железная дорога":
/create_company
        """)
        return
    
    await state.update_data(company_id=company[0], company_name=company[1])
    await message.answer(f"🚆 Создание маршрута для компании: {company[1]}\n\nВведите номер маршрута:")
    await state.set_state(TrainRouteCreation.number)

@dp.message(TrainRouteCreation.number)
async def process_route_number(message: Message, state: FSMContext):
    """Обработка номера маршрута"""
    route_number = message.text.strip()
    await state.update_data(number=route_number)
    await message.answer("🏷️ Введите название маршрута (например, 'Аврора', 'Буревестник'):")
    await state.set_state(TrainRouteCreation.name)

@dp.message(TrainRouteCreation.name)
async def process_route_name(message: Message, state: FSMContext):
    """Обработка названия маршрута"""
    route_name = message.text.strip()
    await state.update_data(name=route_name)
    await message.answer("🧭 Введите направление маршрута (например, 'Москва - Санкт-Петербург'):")
    await state.set_state(TrainRouteCreation.direction)

@dp.message(TrainRouteCreation.direction)
async def process_route_direction(message: Message, state: FSMContext):
    """Обработка направления маршрута"""
    direction = message.text.strip()
    await state.update_data(direction=direction)
    await message.answer("📅 Введите дату и время отправления (формат: ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(TrainRouteCreation.departure_date)

@dp.message(TrainRouteCreation.departure_date)
async def process_route_departure(message: Message, state: FSMContext):
    """Обработка даты отправления"""
    try:
        departure_str = message.text.strip()
        departure_time = datetime.strptime(departure_str, "%d.%m.%Y %H:%M")
        
        if departure_time < datetime.now():
            await message.answer("❌ Дата отправления не может быть в прошлом")
            return
        
        await state.update_data(departure_date=departure_time)
        await message.answer("💰 Введите цену билета:")
        await state.set_state(TrainRouteCreation.price)
        
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")

@dp.message(TrainRouteCreation.price)
async def process_route_price(message: Message, state: FSMContext):
    """Завершение создания маршрута"""
    try:
        price = float(message.text)
        if price <= 0:
            await message.answer("❌ Цена должна быть больше 0")
            return
        
        data = await state.get_data()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Создаем маршрут
        cursor.execute('''
        INSERT INTO train_routes (company_id, route_number, route_name, direction, departure_time, price) 
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['company_id'], data['number'], data['name'], data['direction'], data['departure_date'], price))
        
        route_id = cursor.lastrowid
        
        # Логируем действие
        log_action(message.from_user.id, "route_create", 
                  f"route_id={route_id}, number={data['number']}, name={data['name']}")
        
        conn.commit()
        conn.close()
        
        departure_str = data['departure_date'].strftime("%d.%m.%Y %H:%M")
        
        await message.answer(f"""
✅ Маршрут создан!

ID маршрута: {route_id}
Номер: {data['number']}
Название: {data['name']}
Направление: {data['direction']}
Отправление: {departure_str}
Цена билета: {price:.2f}
Компания: {data['company_name']}

💡 Пользователи могут купить билеты через /buy_ticket
        """)
        
    except ValueError:
        await message.answer("❌ Введите корректную цену (число)")
    finally:
        await state.clear()

@dp.callback_query(F.data == "routes_menu")
async def routes_menu_callback(callback: CallbackQuery):
    """Меню маршрутов"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚆 Доступные маршруты", callback_data="available_routes")],
        [InlineKeyboardButton(text="🎫 Купить билет", callback_data="buy_ticket_menu")],
        [InlineKeyboardButton(text="📋 Мои билеты", callback_data="my_tickets")],
        [InlineKeyboardButton(text="🏢 Создать маршрут", callback_data="create_route_menu")]
    ])
    
    await callback.message.answer("🚆 **Меню маршрутов:**", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "available_routes")
async def available_routes_callback(callback: CallbackQuery):
    """Показать доступные маршруты"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем активные маршруты
    cursor.execute('''
    SELECT r.route_id, r.route_number, r.route_name, r.direction, r.departure_time, r.price, c.company_name
    FROM train_routes r
    JOIN companies c ON r.company_id = c.company_id
    WHERE r.departure_time > datetime('now')
    ORDER BY r.departure_time
    LIMIT 20
    ''')
    
    routes = cursor.fetchall()
    conn.close()
    
    if not routes:
        await callback.message.answer("🚆 Нет доступных маршрутов")
        await callback.answer()
        return
    
    text = "🚆 **Доступные маршруты:**\n\n"
    
    for route in routes:
        route_id, number, name, direction, departure, price, company = route
        departure_time = datetime.strptime(departure, "%Y-%m-%d %H:%M:%S")
        
        text += f"**{number} - {name}**\n"
        text += f"ID: {route_id}\n"
        text += f"Направление: {direction}\n"
        text += f"Отправление: {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"Цена: {price:.2f}\n"
        text += f"Компания: {company}\n"
        text += f"Купить: /buy_ticket_{route_id}\n"
        text += "─" * 30 + "\n"
    
    await callback.message.answer(text)
    await callback.answer()

@dp.message(Command("buy_ticket"))
async def buy_ticket_command(message: Message):
    """Покупка билета"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем доступные маршруты
    cursor.execute('''
    SELECT r.route_id, r.route_number, r.route_name, r.direction, r.departure_time, r.price, c.company_name
    FROM train_routes r
    JOIN companies c ON r.company_id = c.company_id
    WHERE r.departure_time > datetime('now')
    ORDER BY r.departure_time
    LIMIT 10
    ''')
    
    routes = cursor.fetchall()
    conn.close()
    
    if not routes:
        await message.answer("🎫 Нет доступных маршрутов для покупки билетов")
        return
    
    # Создаем инлайн-клавиатуру с маршрутами
    keyboard_buttons = []
    for route in routes:
        route_id, number, name, direction, departure, price, company = route
        departure_time = datetime.strptime(departure, "%Y-%m-%d %H:%M:%S")
        button_text = f"{number} {name} - {price:.2f}"
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"buy_ticket_{route_id}")])
    
    # Добавляем кнопку "Назад"
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer("🎫 **Выберите маршрут для покупки билета:**", reply_markup=reply_markup)

@dp.callback_query(F.data.startswith("buy_ticket_"))
async def process_ticket_buy(callback: CallbackQuery):
    """Обработка покупки билета"""
    route_id = int(callback.data.split("_")[2])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем информацию о маршруте
    cursor.execute('''
    SELECT r.route_number, r.route_name, r.direction, r.departure_time, r.price, c.company_name, c.company_id
    FROM train_routes r
    JOIN companies c ON r.company_id = c.company_id
    WHERE r.route_id = ?
    ''', (route_id,))
    
    route = cursor.fetchone()
    
    if not route:
        await callback.answer("❌ Маршрут не найден")
        return
    
    number, name, direction, departure, price, company, company_id = route
    departure_time = datetime.strptime(departure, "%Y-%m-%d %H:%M:%S")
    
    # Проверяем баланс пользователя
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (callback.from_user.id,))
    balance = cursor.fetchone()[0]
    
    if balance < price:
        await callback.answer("❌ Недостаточно средств")
        conn.close()
        return
    
    # Генерируем номер места
    cursor.execute('SELECT COUNT(*) FROM tickets WHERE route_id = ?', (route_id,))
    tickets_sold = cursor.fetchone()[0]
    seat_number = f"{tickets_sold + 1:02d}"
    
    # Покупка билета
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (price, callback.from_user.id))
    
    # Зачисляем деньги компании (80% от цены)
    company_share = price * 0.8
    cursor.execute('UPDATE companies SET capital = capital + ? WHERE company_id = ?', (company_share, company_id))
    
    # Создаем билет
    cursor.execute('''
    INSERT INTO tickets (route_id, buyer_id, seat_number, price) 
    VALUES (?, ?, ?, ?)
    ''', (route_id, callback.from_user.id, seat_number, price))
    
    ticket_id = cursor.lastrowid
    
    # Логируем транзакцию
    cursor.execute('''
    INSERT INTO transactions (sender_id, receiver_id, amount, description) 
    VALUES (?, ?, ?, ?)
    ''', (callback.from_user.id, company_id, price, f"Покупка билета {number}"))
    
    # Логируем действие
    log_action(callback.from_user.id, "ticket_buy", f"route_id={route_id}, ticket_id={ticket_id}")
    
    conn.commit()
    conn.close()
    
    ticket_info = f"""
✅ Билет куплен!

🎫 **Информация о билете:**
ID билета: {ticket_id}
Маршрут: {number} "{name}"
Направление: {direction}
Компания: {company}
Дата отправления: {departure_time.strftime('%d.%m.%Y %H:%M')}
Место: {seat_number}
Цена: {price:.2f}
Ваш новый баланс: {balance - price:.2f}
    """
    
    await callback.message.answer(ticket_info)
    await callback.answer("Билет успешно куплен!")

@dp.callback_query(F.data == "my_tickets")
async def my_tickets_callback(callback: CallbackQuery):
    """Показать билеты пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT t.ticket_id, r.route_number, r.route_name, r.direction, r.departure_time, t.seat_number, t.price, t.status
    FROM tickets t
    JOIN train_routes r ON t.route_id = r.route_id
    WHERE t.buyer_id = ?
    ORDER BY r.departure_time DESC
    ''', (callback.from_user.id,))
    
    tickets = cursor.fetchall()
    conn.close()
    
    if not tickets:
        await callback.message.answer("🎫 У вас пока нет купленных билетов")
        await callback.answer()
        return
    
    text = "🎫 **Ваши билеты:**\n\n"
    
    for ticket in tickets:
        ticket_id, number, name, direction, departure, seat, price, status = ticket
        departure_time = datetime.strptime(departure, "%Y-%m-%d %H:%M:%S")
        
        status_icon = "✅" if status == 'active' else "❌"
        
        text += f"{status_icon} **Билет #{ticket_id}**\n"
        text += f"Маршрут: {number} \"{name}\"\n"
        text += f"Направление: {direction}\n"
        text += f"Дата: {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"Место: {seat}\n"
        text += f"Цена: {price:.2f}\n"
        text += "─" * 20 + "\n"
    
    await callback.message.answer(text)
    await callback.answer()

@dp.message(Command("create_check"))
async def create_check_command(message: Message, state: FSMContext):
    """Создание чека"""
    await message.answer("🧾 Введите сумму чека:")
    await state.set_state(CheckCreation.amount)

@dp.message(CheckCreation.amount)
async def process_check_amount(message: Message, state: FSMContext):
    """Обработка суммы чека"""
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        
        # Проверяем баланс
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,))
        balance = cursor.fetchone()[0]
        conn.close()
        
        if balance < amount:
            await message.answer(f"❌ Недостаточно средств. Ваш баланс: {balance:.2f}")
            await state.clear()
            return
        
        await state.update_data(amount=amount)
        await message.answer("📝 Введите описание чека:")
        await state.set_state(CheckCreation.description)
        
    except ValueError:
        await message.answer("❌ Введите корректную сумму (число)")

@dp.message(CheckCreation.description)
async def process_check_description(message: Message, state: FSMContext):
    """Завершение создания чека"""
    data = await state.get_data()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Резервируем средства
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (data['amount'], message.from_user.id))
    
    # Создаем чек
    cursor.execute('''
    INSERT INTO checks (sender_id, amount, description) 
    VALUES (?, ?, ?)
    ''', (message.from_user.id, data['amount'], message.text))
    
    check_id = cursor.lastrowid
    
    # Логируем действие
    log_action(message.from_user.id, "check_create", f"check_id={check_id}, amount={data['amount']}")
    
    conn.commit()
    conn.close()
    
    check_info = f"""
🧾 **Чек создан!**

ID чека: {check_id}
Сумма: {data['amount']:.2f}
Описание: {message.text}

Для оплаты чека используйте команду:
/pay_check {check_id}

Или дайте этот ID другому пользователю
    """
    
    await message.answer(check_info)
    await state.clear()

@dp.message(Command("pay_check"))
async def pay_check_command(message: Message):
    """Оплата чека"""
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: /pay_check <ID_чека>")
            return
        
        check_id = int(args[1])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем информацию о чеке
        cursor.execute('''
        SELECT check_id, sender_id, amount, description, claimed 
        FROM checks WHERE check_id = ?
        ''', (check_id,))
        
        check = cursor.fetchone()
        
        if not check:
            await message.answer("❌ Чек не найден")
            conn.close()
            return
        
        check_id, sender_id, amount, description, claimed = check
        
        if claimed:
            await message.answer("❌ Этот чек уже оплачен")
            conn.close()
            return
        
        if sender_id == message.from_user.id:
            await message.answer("❌ Нельзя оплатить свой собственный чек")
            conn.close()
            return
        
        # Оплачиваем чек
        cursor.execute('''
        UPDATE checks SET claimed = 1, claimed_by = ?, claimed_at = datetime('now') 
        WHERE check_id = ?
        ''', (message.from_user.id, check_id))
        
        # Возвращаем средства отправителю (они уже были зарезервированы)
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, sender_id))
        
        # Логируем транзакцию
        cursor.execute('''
        INSERT INTO transactions (sender_id, receiver_id, amount, description) 
        VALUES (?, ?, ?, ?)
        ''', (message.from_user.id, sender_id, amount, f"Оплата чека #{check_id}: {description}"))
        
        # Логируем действие
        log_action(message.from_user.id, "check_pay", f"check_id={check_id}, amount={amount}")
        
        conn.commit()
        conn.close()
        
        await message.answer(f"""
✅ Чек #{check_id} оплачен!

Сумма: {amount:.2f}
Описание: {description}
Получатель: {sender_id}
        """)
        
        # Уведомляем отправителя
        try:
            await bot.send_message(
                sender_id,
                f"""
💰 Ваш чек #{check_id} был оплачен!

Сумма: {amount:.2f}
Оплатил: {message.from_user.id}
Описание: {description}
                """
            )
        except:
            pass
        
    except ValueError:
        await message.answer("❌ Неверный ID чека. Введите число")

@dp.callback_query(F.data == "checks_menu")
async def checks_menu_callback(callback: CallbackQuery):
    """Меню чеков"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Создать чек", callback_data="create_check_menu")],
        [InlineKeyboardButton(text="🧾 Мои чеки", callback_data="my_checks_list")],
        [InlineKeyboardButton(text="💰 Доступные чеки", callback_data="available_checks")],
        [InlineKeyboardButton(text="💳 Оплаченные чеки", callback_data="paid_checks")]
    ])
    
    await callback.message.answer("🧾 **Меню чеков:**", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "create_check_menu")
async def create_check_menu_callback(callback: CallbackQuery, state: FSMContext):
    """Начать создание чека из меню"""
    await callback.message.answer("🧾 Введите сумму чека:")
    await state.set_state(CheckCreation.amount)
    await callback.answer()

@dp.callback_query(F.data == "available_checks")
async def available_checks_callback(callback: CallbackQuery):
    """Показать доступные чеки"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT check_id, amount, description, sender_id, created_at
    FROM checks WHERE claimed = 0
    ORDER BY created_at DESC
    LIMIT 10
    ''')
    
    checks = cursor.fetchall()
    conn.close()
    
    if not checks:
        await callback.message.answer("🧾 Нет доступных чеков для оплаты")
        await callback.answer()
        return
    
    text = "🧾 **Доступные чеки:**\n\n"
    
    for check in checks:
        check_id, amount, description, sender_id, created_at = check
        created_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        
        text += f"💰 **Чек #{check_id}**\n"
        text += f"Сумма: {amount:.2f}\n"
        text += f"Описание: {description}\n"
        text += f"Отправитель: {sender_id}\n"
        text += f"Создан: {created_time.strftime('%d.%m %H:%M')}\n"
        text += f"Оплатить: /pay_check {check_id}\n"
        text += "─" * 20 + "\n"
    
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "my_checks_list")
async def my_checks_list_callback(callback: CallbackQuery):
    """Показать чеки пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Чеки созданные пользователем
    cursor.execute('''
    SELECT check_id, amount, description, claimed, claimed_by, created_at
    FROM checks WHERE sender_id = ?
    ORDER BY created_at DESC
    LIMIT 10
    ''', (callback.from_user.id,))
    
    checks = cursor.fetchall()
    conn.close()
    
    if not checks:
        await callback.message.answer("🧾 Вы еще не создавали чеки")
        await callback.answer()
        return
    
    text = "🧾 **Ваши чеки:**\n\n"
    
    for check in checks:
        check_id, amount, description, claimed, claimed_by, created_at = check
        created_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        
        status = "✅ Оплачен" if claimed else "⏳ Ожидает оплаты"
        
        text += f"**Чек #{check_id}** - {status}\n"
        text += f"Сумма: {amount:.2f}\n"
        text += f"Описание: {description}\n"
        if claimed and claimed_by:
            text += f"Оплатил: {claimed_by}\n"
        text += f"Создан: {created_time.strftime('%d.%m %H:%M')}\n"
        text += "─" * 20 + "\n"
    
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться в главное меню"""
    await start_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "create_route_menu")
async def create_route_menu_callback(callback: CallbackQuery):
    """Меню создания маршрута"""
    await create_route_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "buy_ticket_menu")
async def buy_ticket_menu_callback(callback: CallbackQuery):
    """Меню покупки билета"""
    await buy_ticket_command(callback.message)
    await callback.answer()

# ==================== ОБРАБОТЧИК НЕИЗВЕСТНЫХ КОМАНД ====================
@dp.message()
async def unknown_command(message: Message):
    """Обработка неизвестных команд"""
    await message.answer("🤔 Неизвестная команда. Используйте /help для списка команд")

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        init_db()
        
        logger.info("=" * 50)
        logger.info("🤖 Бот запускается...")
        logger.info(f"👑 ID администратора: {ADMIN_ID}")
        logger.info("=" * 50)
        
        # Запуск бота
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()
        logger.info("👋 Бот остановлен")

if __name__ == "__main__":
    # Проверяем Python версию
    if sys.version_info < (3, 8):
        print("❌ Требуется Python 3.8 или выше")
        sys.exit(1)
    
    # Запускаем бота
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
