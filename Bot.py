import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import random
import string

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "8498581637:AAF4Z59SYbdP9Z2Jk6oM3EnJ0tsXAbQvPDw"
ADMIN_IDS = [6339108316]  # Ваш ID администратора
INITIAL_BALANCE = 1000
DATABASE_FILE = "economic_bot.db"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Классы состояний для FSM
class BusinessStates(StatesGroup):
    waiting_for_business_name = State()
    waiting_for_business_type = State()
    waiting_for_business_description = State()

class CompanyStates(StatesGroup):
    waiting_for_company_name = State()
    waiting_for_company_type = State()
    waiting_for_company_description = State()
    
class RailwayStates(StatesGroup):
    waiting_for_route_number = State()
    waiting_for_route_name = State()
    waiting_for_direction = State()
    waiting_for_departure_date = State()
    waiting_for_ticket_price = State()
    
class TicketStates(StatesGroup):
    waiting_for_route_choice = State()
    waiting_for_ticket_count = State()
    
class TransferStates(StatesGroup):
    waiting_for_receiver_id = State()
    waiting_for_amount = State()
    
class CheckStates(StatesGroup):
    waiting_for_check_amount = State()
    waiting_for_check_description = State()
    
class AdminStates(StatesGroup):
    waiting_for_user_id_for_balance = State()
    waiting_for_balance_amount = State()
    waiting_for_user_id_for_role = State()
    waiting_for_company_id_for_railway = State()

# Инициализация базы данных
def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance REAL DEFAULT 1000,
        role TEXT DEFAULT 'user',
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Бизнесы
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER,
        name TEXT,
        type TEXT,
        description TEXT,
        level INTEGER DEFAULT 1,
        income REAL DEFAULT 100,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users (user_id)
    )
    ''')
    
    # Компании
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER,
        name TEXT,
        type TEXT,
        description TEXT,
        is_railway INTEGER DEFAULT 0,
        balance REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users (user_id)
    )
    ''')
    
    # ЖД маршруты
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS railway_routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        route_number TEXT,
        route_name TEXT,
        direction TEXT,
        departure_date TIMESTAMP,
        ticket_price REAL,
        available_tickets INTEGER DEFAULT 100,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )
    ''')
    
    # Билеты
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        route_id INTEGER,
        purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        quantity INTEGER,
        total_price REAL,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (route_id) REFERENCES railway_routes (id)
    )
    ''')
    
    # Транзакции
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        amount REAL,
        type TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users (user_id),
        FOREIGN KEY (receiver_id) REFERENCES users (user_id)
    )
    ''')
    
    # Чеки
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_code TEXT UNIQUE,
        creator_id INTEGER,
        amount REAL,
        description TEXT,
        is_used INTEGER DEFAULT 0,
        used_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (creator_id) REFERENCES users (user_id),
        FOREIGN KEY (used_by) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Генерация случайного кода чека
def generate_check_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# Получение пользователя
def get_user(user_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Регистрация пользователя
def register_user(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            'INSERT INTO users (user_id, username, full_name, balance) VALUES (?, ?, ?, ?)',
            (user_id, username, full_name, INITIAL_BALANCE)
        )
    
    conn.commit()
    conn.close()

# Обновление баланса
def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

# Создание транзакции
def create_transaction(sender_id: int, receiver_id: int, amount: float, trans_type: str, description: str = ""):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO transactions (sender_id, receiver_id, amount, type, description) VALUES (?, ?, ?, ?, ?)',
        (sender_id, receiver_id, amount, trans_type, description)
    )
    conn.commit()
    conn.close()

# Создание бизнеса
def create_business(owner_id: int, name: str, business_type: str, description: str):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO businesses (owner_id, name, type, description) VALUES (?, ?, ?, ?)',
        (owner_id, name, business_type, description)
    )
    conn.commit()
    conn.close()

# Получение бизнесов пользователя
def get_user_businesses(user_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM businesses WHERE owner_id = ?', (user_id,))
    businesses = cursor.fetchall()
    conn.close()
    return businesses

# Создание компании
def create_company(owner_id: int, name: str, company_type: str, description: str, is_railway: bool = False):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO companies (owner_id, name, type, description, is_railway) VALUES (?, ?, ?, ?, ?)',
        (owner_id, name, company_type, description, 1 if is_railway else 0)
    )
    conn.commit()
    conn.close()

# Получение компаний пользователя
def get_user_companies(user_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM companies WHERE owner_id = ?', (user_id,))
    companies = cursor.fetchall()
    conn.close()
    return companies

# Получение ЖД компаний
def get_railway_companies():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM companies WHERE is_railway = 1')
    companies = cursor.fetchall()
    conn.close()
    return companies

# Создание ЖД маршрута
def create_railway_route(company_id: int, route_number: str, route_name: str, direction: str, departure_date: str, ticket_price: float):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO railway_routes 
        (company_id, route_number, route_name, direction, departure_date, ticket_price) 
        VALUES (?, ?, ?, ?, ?, ?)''',
        (company_id, route_number, route_name, direction, departure_date, ticket_price)
    )
    conn.commit()
    conn.close()

# Получение маршрутов компании
def get_company_routes(company_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM railway_routes WHERE company_id = ?', (company_id,))
    routes = cursor.fetchall()
    conn.close()
    return routes

# Получение всех активных маршрутов
def get_all_routes():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM railway_routes WHERE departure_date > datetime("now")')
    routes = cursor.fetchall()
    conn.close()
    return routes

# Покупка билетов
def buy_tickets(user_id: int, route_id: int, quantity: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получаем информацию о маршруте
    cursor.execute('SELECT ticket_price, available_tickets FROM railway_routes WHERE id = ?', (route_id,))
    route = cursor.fetchone()
    
    if not route:
        conn.close()
        return False, "Маршрут не найден"
    
    ticket_price, available_tickets = route
    
    if available_tickets < quantity:
        conn.close()
        return False, "Недостаточно билетов"
    
    total_price = ticket_price * quantity
    
    # Проверяем баланс пользователя
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    user_balance = cursor.fetchone()[0]
    
    if user_balance < total_price:
        conn.close()
        return False, "Недостаточно средств"
    
    # Списание средств
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (total_price, user_id))
    
    # Уменьшение доступных билетов
    cursor.execute('UPDATE railway_routes SET available_tickets = available_tickets - ? WHERE id = ?', (quantity, route_id))
    
    # Создание записи о билетах
    cursor.execute(
        'INSERT INTO tickets (user_id, route_id, quantity, total_price) VALUES (?, ?, ?, ?)',
        (user_id, route_id, quantity, total_price)
    )
    
    # Получаем ID компании
    cursor.execute('SELECT company_id FROM railway_routes WHERE id = ?', (route_id,))
    company_id = cursor.fetchone()[0]
    
    # Зачисление средств компании
    cursor.execute('UPDATE companies SET balance = balance + ? WHERE id = ?', (total_price, company_id))
    
    conn.commit()
    conn.close()
    return True, f"Вы успешно приобрели {quantity} билет(ов) за {total_price}₽"

# Создание чека
def create_check(creator_id: int, amount: float, description: str):
    check_code = generate_check_code()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO checks (check_code, creator_id, amount, description) VALUES (?, ?, ?, ?)',
        (check_code, creator_id, amount, description)
    )
    conn.commit()
    conn.close()
    return check_code

# Использование чека
def use_check(check_code: str, user_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM checks WHERE check_code = ? AND is_used = 0', (check_code,))
    check = cursor.fetchone()
    
    if not check:
        conn.close()
        return False, "Чек не найден или уже использован"
    
    check_id, _, creator_id, amount, description, _, _, _ = check
    
    # Обновление чека
    cursor.execute('UPDATE checks SET is_used = 1, used_by = ? WHERE id = ?', (user_id, check_id))
    
    # Зачисление средств пользователю
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    
    # Создание транзакции
    cursor.execute(
        'INSERT INTO transactions (sender_id, receiver_id, amount, type, description) VALUES (?, ?, ?, ?, ?)',
        (creator_id, user_id, amount, 'check', f"Использование чека: {description}")
    )
    
    conn.commit()
    conn.close()
    return True, f"Вы успешно использовали чек на сумму {amount}₽"

# Получение чеков пользователя
def get_user_checks(user_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM checks WHERE creator_id = ? ORDER BY created_at DESC LIMIT 10', (user_id,))
    checks = cursor.fetchall()
    conn.close()
    return checks

# Админ функции
def admin_set_balance(user_id: int, amount: float):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def admin_set_role(user_id: int, role: str):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
    conn.commit()
    conn.close()

def admin_make_company_railway(company_id: int):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE companies SET is_railway = 1 WHERE id = ?', (company_id,))
    conn.commit()
    conn.close()

# Клавиатуры
def get_main_keyboard():
    keyboard = ReplyKeyboardBuilder()
    keyboard.add(KeyboardButton(text="💰 Баланс"))
    keyboard.add(KeyboardButton(text="🏢 Мои бизнесы"), KeyboardButton(text="🏭 Мои компании"))
    keyboard.add(KeyboardButton(text="🎫 Купить билет"), KeyboardButton(text="🚆 ЖД маршруты"))
    keyboard.add(KeyboardButton(text="💸 Перевести деньги"), KeyboardButton(text="🧾 Чеки"))
    keyboard.add(KeyboardButton(text="📊 Экономика"), KeyboardButton(text="🆘 Помощь"))
    keyboard.adjust(2)
    return keyboard.as_markup(resize_keyboard=True)

def get_admin_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💰 Установить баланс", callback_data="admin_set_balance"))
    keyboard.add(InlineKeyboardButton(text="👑 Установить роль", callback_data="admin_set_role"))
    keyboard.add(InlineKeyboardButton(text="🚆 Сделать компанию ЖД", callback_data="admin_make_railway"))
    keyboard.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    keyboard.adjust(1)
    return keyboard.as_markup()

def get_business_types_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🍽️ Ресторан", callback_data="business_restaurant"))
    keyboard.add(InlineKeyboardButton(text="🛍️ Магазин", callback_data="business_shop"))
    keyboard.add(InlineKeyboardButton(text="💻 IT компания", callback_data="business_it"))
    keyboard.add(InlineKeyboardButton(text="🏢 Недвижимость", callback_data="business_real_estate"))
    keyboard.add(InlineKeyboardButton(text="🚗 Автосалон", callback_data="business_car_dealership"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def get_company_types_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🚆 Железная дорога", callback_data="company_railway"))
    keyboard.add(InlineKeyboardButton(text="✈️ Авиакомпания", callback_data="company_airline"))
    keyboard.add(InlineKeyboardButton(text="🚌 Автобусная", callback_data="company_bus"))
    keyboard.add(InlineKeyboardButton(text="🚢 Судоходная", callback_data="company_shipping"))
    keyboard.add(InlineKeyboardButton(text="🏭 Производство", callback_data="company_manufacturing"))
    keyboard.adjust(2)
    return keyboard.as_markup()

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    register_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_text = """
    🎉 Добро пожаловать в Экономический Бот! 🎉

    💰 **Основные возможности:**
    • Баланс и переводы между пользователями
    • Создание и управление бизнесами
    • Создание компаний (в том числе ЖД)
    • Покупка билетов у ЖД компаний
    • Создание и использование чеков
    • Управление ЖД маршрутами

    📊 **Быстрые команды:**
    /balance - Ваш баланс
    /business - Создать бизнес
    /company - Создать компанию
    /ticket - Купить билет
    /route - Создать маршрут (для ЖД компаний)
    /check - Создать чек
    /transfer - Перевести деньги
    /help - Помощь

    Используйте меню ниже для навигации! 🚀
    """
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# Команда /help
@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
    🆘 **Помощь по командам:**

    💰 **Финансы:**
    /balance - Показать баланс
    /transfer - Перевести деньги другому пользователю

    🏢 **Бизнес:**
    /business - Создать новый бизнес
    /mybusiness - Показать мои бизнесы

    🏭 **Компании:**
    /company - Создать компанию
    /mycompanies - Показать мои компании
    /railway_routes - Показать ЖД маршруты

    🎫 **Билеты:**
    /ticket - Купить билет на поезд
    /mytickets - Мои билеты

    🧾 **Чеки:**
    /check_create - Создать чек
    /check_use - Использовать чек
    /mychecks - Мои чеки

    🚆 **Для ЖД компаний:**
    /route_create - Создать маршрут

    👑 **Админ команды:**
    /admin - Панель администратора
    """
    
    if message.from_user.id in ADMIN_IDS:
        help_text += "\n\n👑 **Вы администратор!** Доступны специальные команды."
    
    await message.answer(help_text, parse_mode="Markdown")

# Команда /balance
@dp.message(Command("balance"))
@dp.message(F.text == "💰 Баланс")
async def cmd_balance(message: Message):
    user = get_user(message.from_user.id)
    if user:
        balance = user[3]
        await message.answer(f"💰 **Ваш баланс:** {balance}₽\n\n📊 **ID для переводов:** `{message.from_user.id}`", parse_mode="Markdown")
    else:
        await message.answer("❌ Пользователь не найден!")

# Команда /transfer
@dp.message(Command("transfer"))
@dp.message(F.text == "💸 Перевести деньги")
async def cmd_transfer(message: Message, state: FSMContext):
    await message.answer("💸 **Перевод денег**\n\nВведите ID пользователя, которому хотите перевести:")
    await state.set_state(TransferStates.waiting_for_receiver_id)

@dp.message(TransferStates.waiting_for_receiver_id)
async def process_receiver_id(message: Message, state: FSMContext):
    try:
        receiver_id = int(message.text)
        if receiver_id == message.from_user.id:
            await message.answer("❌ Нельзя переводить деньги самому себе!")
            await state.clear()
            return
            
        receiver = get_user(receiver_id)
        if not receiver:
            await message.answer("❌ Пользователь с таким ID не найден!")
            await state.clear()
            return
            
        await state.update_data(receiver_id=receiver_id)
        await message.answer(f"✅ Пользователь найден: {receiver[2]}\n\nВведите сумму для перевода:")
        await state.set_state(TransferStates.waiting_for_amount)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректный ID (число)")

@dp.message(TransferStates.waiting_for_amount)
async def process_transfer_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!")
            await state.clear()
            return
            
        user_data = await state.get_data()
        receiver_id = user_data['receiver_id']
        
        sender = get_user(message.from_user.id)
        if sender[3] < amount:
            await message.answer("❌ Недостаточно средств на балансе!")
            await state.clear()
            return
        
        # Выполняем перевод
        update_balance(message.from_user.id, -amount)
        update_balance(receiver_id, amount)
        
        # Создаем запись о транзакции
        create_transaction(
            message.from_user.id, 
            receiver_id, 
            amount, 
            "transfer",
            f"Перевод от {sender[2]}"
        )
        
        receiver = get_user(receiver_id)
        
        await message.answer(f"✅ Успешно переведено {amount}₽ пользователю {receiver[2]}")
        
        # Уведомляем получателя
        try:
            await bot.send_message(
                receiver_id,
                f"💰 Вы получили перевод {amount}₽ от {sender[2]}"
            )
        except:
            pass
            
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную сумму (число)")

# Команда /business
@dp.message(Command("business"))
@dp.message(F.text == "🏢 Мои бизнесы")
async def cmd_business(message: Message, state: FSMContext):
    businesses = get_user_businesses(message.from_user.id)
    
    if not businesses and message.text != "🏢 Мои бизнесы":
        await message.answer("🏢 **Создание бизнеса**\n\nВведите название вашего бизнеса:")
        await state.set_state(BusinessStates.waiting_for_business_name)
    elif businesses:
        text = "🏢 **Ваши бизнесы:**\n\n"
        for business in businesses:
            text += f"**{business[2]}** ({business[3]})\n"
            text += f"Уровень: {business[5]}\n"
            text += f"Доход: {business[6]}₽/день\n"
            text += f"Описание: {business[4]}\n"
            text += "─" * 20 + "\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="➕ Создать новый бизнес", callback_data="create_business"))
        keyboard.add(InlineKeyboardButton(text="💼 Управлять бизнесами", callback_data="manage_businesses"))
        
        await message.answer(text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
    else:
        await message.answer("🏢 **Создание бизнеса**\n\nВведите название вашего бизнеса:")
        await state.set_state(BusinessStates.waiting_for_business_name)

@dp.message(BusinessStates.waiting_for_business_name)
async def process_business_name(message: Message, state: FSMContext):
    await state.update_data(business_name=message.text)
    await message.answer("🏢 **Выберите тип бизнеса:**", reply_markup=get_business_types_keyboard())
    await state.set_state(BusinessStates.waiting_for_business_type)

@dp.callback_query(F.data.startswith("business_"))
async def process_business_type(callback: CallbackQuery, state: FSMContext):
    business_type_map = {
        "business_restaurant": "Ресторан",
        "business_shop": "Магазин",
        "business_it": "IT компания",
        "business_real_estate": "Недвижимость",
        "business_car_dealership": "Автосалон"
    }
    
    business_type = business_type_map.get(callback.data, "Другое")
    await state.update_data(business_type=business_type)
    
    await callback.message.edit_text(f"🏢 **Тип бизнеса:** {business_type}\n\n📝 Введите описание вашего бизнеса:")
    await state.set_state(BusinessStates.waiting_for_business_description)
    await callback.answer()

@dp.message(BusinessStates.waiting_for_business_description)
async def process_business_description(message: Message, state: FSMContext):
    user_data = await state.get_data()
    business_name = user_data['business_name']
    business_type = user_data['business_type']
    
    create_business(message.from_user.id, business_name, business_type, message.text)
    
    await message.answer(f"✅ **Бизнес создан!**\n\n🏢 **Название:** {business_name}\n📊 **Тип:** {business_type}\n📝 **Описание:** {message.text}")
    await state.clear()

# Команда /company
@dp.message(Command("company"))
async def cmd_company(message: Message, state: FSMContext):
    await message.answer("🏭 **Создание компании**\n\nВведите название вашей компании:")
    await state.set_state(CompanyStates.waiting_for_company_name)

@dp.message(CompanyStates.waiting_for_company_name)
async def process_company_name(message: Message, state: FSMContext):
    await state.update_data(company_name=message.text)
    await message.answer("🏭 **Выберите тип компании:**", reply_markup=get_company_types_keyboard())
    await state.set_state(CompanyStates.waiting_for_company_type)

@dp.callback_query(F.data.startswith("company_"))
async def process_company_type(callback: CallbackQuery, state: FSMContext):
    company_type_map = {
        "company_railway": "Железная дорога",
        "company_airline": "Авиакомпания",
        "company_bus": "Автобусная компания",
        "company_shipping": "Судоходная компания",
        "company_manufacturing": "Производственная компания"
    }
    
    company_type = company_type_map.get(callback.data, "Другое")
    is_railway = callback.data == "company_railway"
    
    await state.update_data(company_type=company_type, is_railway=is_railway)
    
    await callback.message.edit_text(f"🏭 **Тип компании:** {company_type}\n\n📝 Введите описание вашей компании:")
    await state.set_state(CompanyStates.waiting_for_company_description)
    await callback.answer()

@dp.message(CompanyStates.waiting_for_company_description)
async def process_company_description(message: Message, state: FSMContext):
    user_data = await state.get_data()
    company_name = user_data['company_name']
    company_type = user_data['company_type']
    is_railway = user_data['is_railway']
    
    create_company(message.from_user.id, company_name, company_type, message.text, is_railway)
    
    railway_text = " (🚆 ЖД компания)" if is_railway else ""
    await message.answer(f"✅ **Компания создана!**{railway_text}\n\n🏭 **Название:** {company_name}\n📊 **Тип:** {company_type}\n📝 **Описание:** {message.text}")
    await state.clear()

# Команда /mycompanies
@dp.message(Command("mycompanies"))
@dp.message(F.text == "🏭 Мои компании")
async def cmd_mycompanies(message: Message):
    companies = get_user_companies(message.from_user.id)
    
    if not companies:
        await message.answer("❌ У вас еще нет компаний. Создайте первую командой /company")
        return
    
    text = "🏭 **Ваши компании:**\n\n"
    for company in companies:
        railway_status = "🚆 ЖД" if company[5] == 1 else "➖ Не ЖД"
        text += f"**{company[2]}** ({company[3]}) {railway_status}\n"
        text += f"Баланс компании: {company[6]}₽\n"
        text += f"Описание: {company[4]}\n"
        
        if company[5] == 1:
            routes = get_company_routes(company[0])
            text += f"Маршрутов: {len(routes)}\n"
            
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="➕ Создать маршрут", callback_data=f"create_route_{company[0]}"))
            keyboard.add(InlineKeyboardButton(text="📋 Показать маршруты", callback_data=f"show_routes_{company[0]}"))
            
            text += "─" * 20 + "\n"
            await message.answer(text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
            text = ""
    
    if text:
        await message.answer(text, parse_mode="Markdown")

# Команда /route_create
@dp.message(Command("route_create"))
async def cmd_route_create(message: Message, state: FSMContext):
    companies = get_user_companies(message.from_user.id)
    railway_companies = [c for c in companies if c[5] == 1]
    
    if not railway_companies:
        await message.answer("❌ У вас нет ЖД компаний. Сначала создайте ЖД компанию!")
        return
    
    keyboard = InlineKeyboardBuilder()
    for company in railway_companies:
        keyboard.add(InlineKeyboardButton(text=f"{company[2]}", callback_data=f"route_for_company_{company[0]}"))
    
    await message.answer("🚆 **Создание маршрута**\n\nВыберите компанию для создания маршрута:", reply_markup=keyboard.as_markup())
    await state.set_state(RailwayStates.waiting_for_route_number)

@dp.callback_query(F.data.startswith("route_for_company_"))
async def process_route_company(callback: CallbackQuery, state: FSMContext):
    company_id = int(callback.data.split("_")[3])
    await state.update_data(company_id=company_id)
    
    await callback.message.edit_text("🚆 **Создание маршрута**\n\nВведите номер маршрута (например, 001А):")
    await state.set_state(RailwayStates.waiting_for_route_number)
    await callback.answer()

@dp.message(RailwayStates.waiting_for_route_number)
async def process_route_number(message: Message, state: FSMContext):
    await state.update_data(route_number=message.text)
    await message.answer("🚆 **Введите название маршрута (например, Аврора, Буревестник):")
    await state.set_state(RailwayStates.waiting_for_route_name)

@dp.message(RailwayStates.waiting_for_route_name)
async def process_route_name(message: Message, state: FSMContext):
    await state.update_data(route_name=message.text)
    await message.answer("🚆 **Введите направление (например, Москва - Санкт-Петербург):")
    await state.set_state(RailwayStates.waiting_for_direction)

@dp.message(RailwayStates.waiting_for_direction)
async def process_route_direction(message: Message, state: FSMContext):
    await state.update_data(direction=message.text)
    await message.answer("🚆 **Введите дату отправления (в формате ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(RailwayStates.waiting_for_departure_date)

@dp.message(RailwayStates.waiting_for_departure_date)
async def process_departure_date(message: Message, state: FSMContext):
    try:
        departure_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        await state.update_data(departure_date=departure_date.strftime("%Y-%m-%d %H:%M:%S"))
        await message.answer("🚆 **Введите цену билета:")
        await state.set_state(RailwayStates.waiting_for_ticket_price)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")

@dp.message(RailwayStates.waiting_for_ticket_price)
async def process_ticket_price(message: Message, state: FSMContext):
    try:
        ticket_price = float(message.text)
        user_data = await state.get_data()
        
        create_railway_route(
            user_data['company_id'],
            user_data['route_number'],
            user_data['route_name'],
            user_data['direction'],
            user_data['departure_date'],
            ticket_price
        )
        
        await message.answer(f"""
✅ **Маршрут создан!**

🚆 **Номер:** {user_data['route_number']}
📋 **Название:** {user_data['route_name']}
📍 **Направление:** {user_data['direction']}
📅 **Отправление:** {user_data['departure_date']}
💰 **Цена билета:** {ticket_price}₽
        """)
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную цену (число)")

# Команда /railway_routes
@dp.message(Command("railway_routes"))
@dp.message(F.text == "🚆 ЖД маршруты")
async def cmd_railway_routes(message: Message):
    routes = get_all_routes()
    
    if not routes:
        await message.answer("❌ Нет доступных ЖД маршрутов.")
        return
    
    text = "🚆 **Доступные ЖД маршруты:**\n\n"
    for route in routes:
        departure_date = datetime.strptime(route[5], "%Y-%m-%d %H:%M:%S")
        text += f"**{route[3]}** (№{route[2]})\n"
        text += f"📍 {route[4]}\n"
        text += f"📅 {departure_date.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"💰 {route[6]}₽ (осталось: {route[7]})\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🎫 Купить билет", callback_data="buy_ticket_menu"))
    
    await message.answer(text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")

# Команда /ticket
@dp.message(Command("ticket"))
@dp.message(F.text == "🎫 Купить билет")
async def cmd_ticket(message: Message, state: FSMContext):
    routes = get_all_routes()
    
    if not routes:
        await message.answer("❌ Нет доступных ЖД маршрутов для покупки билетов.")
        return
    
    keyboard = InlineKeyboardBuilder()
    for route in routes[:10]:  # Ограничиваем 10 маршрутами
        departure_date = datetime.strptime(route[5], "%Y-%m-%d %H:%M:%S")
        keyboard.add(InlineKeyboardButton(
            text=f"{route[3]} - {route[4][:20]}...",
            callback_data=f"select_route_{route[0]}"
        ))
    
    keyboard.adjust(1)
    await message.answer("🎫 **Выберите маршрут для покупки билета:**", reply_markup=keyboard.as_markup())
    await state.set_state(TicketStates.waiting_for_route_choice)

@dp.callback_query(F.data.startswith("select_route_"))
async def process_route_choice(callback: CallbackQuery, state: FSMContext):
    route_id = int(callback.data.split("_")[2])
    await state.update_data(route_id=route_id)
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM railway_routes WHERE id = ?', (route_id,))
    route = cursor.fetchone()
    conn.close()
    
    if route:
        departure_date = datetime.strptime(route[5], "%Y-%m-%d %H:%M:%S")
        await callback.message.edit_text(f"""
🎫 **Выбран маршрут:**

🚆 **Номер:** {route[2]}
📋 **Название:** {route[3]}
📍 **Направление:** {route[4]}
📅 **Отправление:** {departure_date.strftime('%d.%m.%Y %H:%M')}
💰 **Цена билета:** {route[6]}₽
🎟️ **Доступно билетов:** {route[7]}

Введите количество билетов:
        """)
        await state.set_state(TicketStates.waiting_for_ticket_count)
    await callback.answer()

@dp.message(TicketStates.waiting_for_ticket_count)
async def process_ticket_count(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            await message.answer("❌ Количество должно быть больше 0!")
            await state.clear()
            return
        
        user_data = await state.get_data()
        success, result = buy_tickets(message.from_user.id, user_data['route_id'], quantity)
        
        if success:
            await message.answer(f"✅ {result}")
        else:
            await message.answer(f"❌ {result}")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное количество (целое число)")

# Команда /check_create
@dp.message(Command("check_create"))
async def cmd_check_create(message: Message, state: FSMContext):
    await message.answer("🧾 **Создание чека**\n\nВведите сумму чека:")
    await state.set_state(CheckStates.waiting_for_check_amount)

@dp.message(CheckStates.waiting_for_check_amount)
async def process_check_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!")
            await state.clear()
            return
        
        user = get_user(message.from_user.id)
        if user[3] < amount:
            await message.answer("❌ Недостаточно средств на балансе!")
            await state.clear()
            return
        
        await state.update_data(amount=amount)
        await message.answer("🧾 **Введите описание чека (необязательно):**")
        await state.set_state(CheckStates.waiting_for_check_description)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную сумму (число)")

@dp.message(CheckStates.waiting_for_check_description)
async def process_check_description(message: Message, state: FSMContext):
    user_data = await state.get_data()
    amount = user_data['amount']
    
    # Списываем средства
    update_balance(message.from_user.id, -amount)
    
    # Создаем чек
    check_code = create_check(message.from_user.id, amount, message.text)
    
    await message.answer(f"""
✅ **Чек создан!**

💰 **Сумма:** {amount}₽
📝 **Описание:** {message.text}
🔢 **Код чека:** `{check_code}`

📤 **Отправьте этот код другому пользователю, чтобы он мог использовать чек.**
    """, parse_mode="Markdown")
    
    await state.clear()

# Команда /check_use
@dp.message(Command("check_use"))
async def cmd_check_use(message: Message):
    await message.answer("🧾 **Использование чека**\n\nВведите код чека:")

@dp.message(F.text.regexp(r'^[A-Z0-9]{10}$'))
async def process_check_use(message: Message):
    success, result = use_check(message.text, message.from_user.id)
    
    if success:
        await message.answer(f"✅ {result}")
    else:
        await message.answer(f"❌ {result}")

# Команда /mychecks
@dp.message(Command("mychecks"))
@dp.message(F.text == "🧾 Чеки")
async def cmd_mychecks(message: Message):
    checks = get_user_checks(message.from_user.id)
    
    if not checks:
        await message.answer("❌ У вас еще нет созданных чеков.")
        return
    
    text = "🧾 **Ваши чеки:**\n\n"
    for check in checks:
        status = "✅ Использован" if check[5] == 1 else "⏳ Ожидает"
        used_by = f" (пользователем {check[7]})" if check[5] == 1 else ""
        text += f"🔢 **Код:** `{check[1]}`\n"
        text += f"💰 **Сумма:** {check[3]}₽\n"
        text += f"📝 **Описание:** {check[4]}\n"
        text += f"📊 **Статус:** {status}{used_by}\n"
        text += "─" * 20 + "\n"
    
    await message.answer(text, parse_mode="Markdown")

# Команда /admin
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав администратора!")
        return
    
    admin_text = """
👑 **Панель администратора**

**Доступные команды:**
• Установить баланс пользователю
• Изменить роль пользователя
• Сделать компанию ЖД компанией
• Просмотр статистики
    """
    
    await message.answer(admin_text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_set_balance")
async def admin_set_balance_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав!")
        return
    
    await callback.message.edit_text("💰 **Установка баланса**\n\nВведите ID пользователя:")
    await state.set_state(AdminStates.waiting_for_user_id_for_balance)
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id_for_balance)
async def admin_process_user_id_balance(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        user = get_user(user_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден!")
            await state.clear()
            return
        
        await state.update_data(admin_user_id=user_id)
        await message.answer(f"👤 **Пользователь:** {user[2]}\n💰 **Текущий баланс:** {user[3]}₽\n\nВведите новый баланс:")
        await state.set_state(AdminStates.waiting_for_balance_amount)
    except ValueError:
        await message.answer("❌ Введите корректный ID!")

@dp.message(AdminStates.waiting_for_balance_amount)
async def admin_process_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        user_data = await state.get_data()
        user_id = user_data['admin_user_id']
        
        admin_set_balance(user_id, amount)
        
        user = get_user(user_id)
        await message.answer(f"✅ Баланс пользователя {user[2]} установлен на {amount}₽")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректную сумму!")

@dp.callback_query(F.data == "admin_set_role")
async def admin_set_role_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав!")
        return
    
    await callback.message.edit_text("👑 **Установка роли**\n\nВведите ID пользователя:")
    await state.set_state(AdminStates.waiting_for_user_id_for_role)
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id_for_role)
async def admin_process_user_id_role(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        user = get_user(user_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден!")
            await state.clear()
            return
        
        await state.update_data(admin_role_user_id=user_id)
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="👤 Пользователь", callback_data="role_user"))
        keyboard.add(InlineKeyboardButton(text="👑 Администратор", callback_data="role_admin"))
        keyboard.add(InlineKeyboardButton(text="🚆 ЖД Директор", callback_data="role_railway"))
        
        await message.answer(f"👤 **Пользователь:** {user[2]}\n🎭 **Текущая роль:** {user[4]}\n\nВыберите новую роль:", reply_markup=keyboard.as_markup())
    except ValueError:
        await message.answer("❌ Введите корректный ID!")

@dp.callback_query(F.data.startswith("role_"))
async def admin_process_role(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав!")
        return
    
    role_map = {
        "role_user": "user",
        "role_admin": "admin",
        "role_railway": "railway_director"
    }
    
    role = role_map.get(callback.data)
    user_data = await state.get_data()
    user_id = user_data['admin_role_user_id']
    
    admin_set_role(user_id, role)
    
    user = get_user(user_id)
    await callback.message.edit_text(f"✅ Роль пользователя {user[2]} изменена на '{role}'")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "admin_make_railway")
async def admin_make_railway_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав!")
        return
    
    await callback.message.edit_text("🚆 **Назначение ЖД компании**\n\nВведите ID компании:")
    await state.set_state(AdminStates.waiting_for_company_id_for_railway)
    await callback.answer()

@dp.message(AdminStates.waiting_for_company_id_for_railway)
async def admin_process_company_id_railway(message: Message, state: FSMContext):
    try:
        company_id = int(message.text)
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM companies WHERE id = ?', (company_id,))
        company = cursor.fetchone()
        conn.close()
        
        if not company:
            await message.answer("❌ Компания не найдена!")
            await state.clear()
            return
        
        admin_make_company_railway(company_id)
        await message.answer(f"✅ Компания '{company[2]}' теперь является ЖД компанией!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректный ID!")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав!")
        return
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Общая статистика
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM businesses')
    total_businesses = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM companies')
    total_companies = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM railway_routes')
    total_routes = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_money = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM tickets')
    total_tickets = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""
📊 **Статистика системы:**

👥 **Пользователи:** {total_users}
🏢 **Бизнесы:** {total_businesses}
🏭 **Компании:** {total_companies}
🚆 **ЖД маршруты:** {total_routes}
🎫 **Проданные билеты:** {total_tickets}
💰 **Общая сумма денег в системе:** {total_money}₽
    """
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

# Команда /economy
@dp.message(Command("economy"))
@dp.message(F.text == "📊 Экономика")
async def cmd_economy(message: Message):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_money = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM businesses')
    total_businesses = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM companies')
    total_companies = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM railway_routes')
    total_routes = cursor.fetchone()[0]
    
    # Топ 5 пользователей по балансу
    cursor.execute('SELECT full_name, balance FROM users ORDER BY balance DESC LIMIT 5')
    top_users = cursor.fetchall()
    
    # Топ 5 компаний по балансу
    cursor.execute('SELECT name, balance FROM companies ORDER BY balance DESC LIMIT 5')
    top_companies = cursor.fetchall()
    
    conn.close()
    
    economy_text = f"""
📊 **Экономическая статистика:**

💰 **Общая экономика:**
• Всего денег в системе: {total_money}₽
• Пользователей: {total_users}
• Бизнесов: {total_businesses}
• Компаний: {total_companies}
• ЖД маршрутов: {total_routes}

👑 **Топ-5 пользователей по балансу:**
"""
    
    for i, (name, balance) in enumerate(top_users, 1):
        economy_text += f"{i}. {name}: {balance}₽\n"
    
    economy_text += "\n🏭 **Топ-5 компаний по балансу:**\n"
    
    for i, (name, balance) in enumerate(top_companies, 1):
        economy_text += f"{i}. {name}: {balance}₽\n"
    
    await message.answer(economy_text, parse_mode="Markdown")

# Обработчик кнопок создания
@dp.callback_query(F.data == "create_business")
async def create_business_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🏢 **Создание бизнеса**\n\nВведите название вашего бизнеса:")
    await state.set_state(BusinessStates.waiting_for_business_name)
    await callback.answer()

@dp.callback_query(F.data.startswith("create_route_"))
async def create_route_callback(callback: CallbackQuery, state: FSMContext):
    company_id = int(callback.data.split("_")[2])
    await state.update_data(company_id=company_id)
    
    await callback.message.edit_text("🚆 **Создание маршрута**\n\nВведите номер маршрута (например, 001А):")
    await state.set_state(RailwayStates.waiting_for_route_number)
    await callback.answer()

@dp.callback_query(F.data.startswith("show_routes_"))
async def show_routes_callback(callback: CallbackQuery):
    company_id = int(callback.data.split("_")[2])
    routes = get_company_routes(company_id)
    
    if not routes:
        await callback.message.edit_text("❌ У этой компании еще нет маршрутов.")
        await callback.answer()
        return
    
    text = "🚆 **Маршруты компании:**\n\n"
    for route in routes:
        departure_date = datetime.strptime(route[5], "%Y-%m-%d %H:%M:%S")
        text += f"**{route[3]}** (№{route[2]})\n"
        text += f"📍 {route[4]}\n"
        text += f"📅 {departure_date.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"💰 {route[6]}₽ (осталось: {route[7]})\n"
        text += "─" * 20 + "\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

# Главная функция
async def main():
    # Инициализация базы данных
    init_database()
    
    logger.info("Бот запущен!")
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
