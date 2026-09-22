import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os
import difflib

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Form(StatesGroup):
    name = State()
    phone = State()
    time = State()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_sheets_client():
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SHEETS_CREDENTIALS"), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client

def save_to_sheets(user_data: dict):
    try:
        client = get_sheets_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet("Applications")
        now = datetime.now()
        row = [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M"),
            user_data['telegram_id'],
            user_data.get('username', 'N/A'),
            user_data['name'],
            user_data['phone'],
            user_data['time'],
            "Новая"
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        logging.error(f"Ошибка записи в Google Sheets: {e}")
        with open("backup.txt", "a", encoding="utf-8") as f:
            f.write(str(user_data) + "\n")
        return False

def log_suspicious(user_id: int, username: str, action: str, reason: str):
    """Логирует подозрительные действия в Google Sheets (Logs)."""
    try:
        client = get_sheets_client()
        log_sheet = client.open(SPREADSHEET_NAME).worksheet("Logs")
        now = datetime.now()
        log_sheet.append_row([
            user_id, username or "N/A", action, reason,
            now.strftime("%Y-%m-%d %H:%M:%S")
        ])
    except Exception as e:
        logging.error(f"Ошибка логирования: {e}")


def validate_name(name: str) -> bool:
    name = name.strip().lower()
    if len(name) < 2:
        return False
    words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', name)
    bad_words = ['хуй', 'пизда', 'бля', 'еба', 'ебу', 'ебал', 'сука', 'мудак', 'fuck', 'shit']
    if any(word in bad_words for word in words):
        return False
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$', name):
        return False
    return True


def validate_phone(phone: str) -> bool:
    phone = phone.strip()
    if phone.startswith('='):
        return False
    if not re.match(r'^[\d\+\-\(\)\s]+$', phone):
        return False

    digits = re.sub(r'\D', '', phone)
    if not (10 <= len(digits) <= 15):
        return False
    if len(set(digits)) <= 1:
        return False
    return True

def validate_time(time_str: str) -> bool:
    time_str = time_str.strip().lower()
    if not time_str:
        return False
    keywords = ['сегодня', 'завтра', 'понедельник', 'вторник', 'среду', 'четверг',
                'пятницу', 'субботу', 'воскресенье', 'утро', 'день', 'вечер', ':', 'после', 'до', 'day', 'today', 'tomorrow']
    if any(word in time_str for word in keywords):
        return True
    if re.search(r'\d', time_str):
        return True
    return False

user_message_times = defaultdict(list)
user_application_counts = defaultdict(int)
blocked_users = {}
daily_reset = {}

MESSAGE_LIMIT_PER_MINUTE = 20
BLOCK_DURATION = 10 * 60
MAX_APPLICATIONS_PER_DAY = 3

def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    user_message_times[user_id] = [t for t in user_message_times[user_id] if now - t < 60]
    if len(user_message_times[user_id]) >= MESSAGE_LIMIT_PER_MINUTE:
        blocked_users[user_id] = now + BLOCK_DURATION
        return True
    user_message_times[user_id].append(now)
    return False

def check_daily_applications(user_id: int) -> bool:
    today = datetime.now().date()
    if daily_reset.get(user_id) != today:
        user_application_counts[user_id] = 0
        daily_reset[user_id] = today
    return user_application_counts[user_id] < MAX_APPLICATIONS_PER_DAY

FAQ = {
    'цена': 'Стоимость наших услуг начинается от 1000 рублей. Точную цену уточнит менеджер.',
    'режим работы': 'Мы работаем ежедневно с 9:00 до 21:00.',
    'адрес': 'Наш адрес: г. Владивосток, ул. Владивостокская, д. 1.',
    'выходной': 'Мы работаем без выходных! С 9:00 до 21:00.',
    'price': 'Our services start from 1000 rubles. The manager will clarify the exact price.',
    'hours': 'We work daily from 9:00 to 21:00.',
}

def find_faq_answer(text: str) -> str | None:
    text_lower = text.lower()
    for key, answer in FAQ.items():
        if key in text_lower:
            return answer
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in blocked_users and time.time() < blocked_users[user_id]:
        await message.answer("Вы временно заблокированы. Попробуйте позже.")
        return
    await state.set_state(Form.name)
    await message.answer("🦷 Здравствуйте! Я — бот стоматологии «32 зуба». Помогу вам записаться на приём. Как Вас зовут? 😊")


@dp.message(Form.name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вы вышли из процесса записи. Пожалуйста, введите команду заново.")
        return
    if is_rate_limited(user_id):
        await message.answer("Слишком много сообщений. Подождите 10 минут.")
        return
    name = message.text.strip()
    if not validate_name(name) or re.search(r'http|www\.|\.ru|\.com', name, re.IGNORECASE):
        log_suspicious(user_id, message.from_user.username, "Неверное имя", name)
        await message.answer("Пожалуйста, введите настоящее имя (минимум 2 символа).")
        return
    await state.update_data(name=name, telegram_id=user_id, username=message.from_user.username)
    await state.set_state(Form.phone)
    await message.answer(f"Отлично, {name}! 📱 Теперь укажите ваш номер телефона в формате +7 XXX XXX-XX-XX.")

@dp.message(Form.phone, F.text)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip()
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вы вышли из процесса записи. Пожалуйста, введите команду заново.")
        return
    if not validate_phone(phone):
        log_suspicious(user_id, message.from_user.username, "Неверный телефон", phone)
        await message.answer("Похоже, номер введён неверно. Пожалуйста, введите номер в формате +7 XXX XXX-XX-XX.")
        return
    await state.update_data(phone=phone)
    await state.set_state(Form.time)
    await message.answer("Супер! 🕐 Когда вам удобно? Напишите, например: «Завтра после 15:00».")

@dp.message(Form.time, F.text)
async def process_time(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    time_str = message.text.strip()
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вы вышли из процесса записи. Пожалуйста, введите команду заново.")
        return
    if not validate_time(time_str):
        log_suspicious(user_id, message.from_user.username, "Неверное время", time_str)
        await message.answer("Уточните, пожалуйста, когда вам удобно: сегодня, завтра или в конкретный день?")
        return
    data = await state.get_data()
    data['time'] = time_str
    if not check_daily_applications(user_id):
        await message.answer("Вы уже оставили несколько заявок. Менеджер с вами свяжется.")
        await state.clear()
        return
    success = save_to_sheets(data)
    if success:
        user_application_counts[user_id] += 1
    await state.clear()
    await message.answer(f"Спасибо, {data['name']}! ✅ Мы получили вашу заявку. Менеджер стоматологии «32 зуба» свяжется с вами в ближайшее время! 🦷✨")

# АДМИН-КОМАНДЫ
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    try:
        client = get_sheets_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet("Applications")
        records = sheet.get_all_records()

        today_str = datetime.now().strftime("%Y-%m-%d")
        apps_today = sum(1 for row in records if str(row.get("Дата", "")) == today_str)
        blocked_count = len(blocked_users)

        await message.answer(
            f"📊 Статистика:\n"
            f"Заявок за сегодня: {apps_today}\n"
            f"Заблокированных: {blocked_count}\n\n"
            f"Последние 10 заявок смотрите в Google Sheets."
        )
    except Exception as e:
        await message.answer(f"Ошибка получения статистики: {e}")


@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        import openpyxl
        client = get_sheets_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet("Applications")
        records = sheet.get_all_records()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Дата", "Время", "Telegram ID", "Username", "Имя", "Телефон", "Удобное время", "Статус"])
        for record in records:
            ws.append(list(record.values()))

        wb.save("export.xlsx")

        document = types.FSInputFile("export.xlsx")
        await message.answer_document(document, caption="Выгрузка всех заявок")

    except Exception as e:
        await message.answer(f"Ошибка экспорта: {e}")

@dp.message(Command("block"))
async def cmd_block(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /block [ID]")
            return
        block_id = int(parts[1])
        blocked_users[block_id] = time.time() + 365 * 24 * 3600
        await message.answer(f"Пользователь {block_id} заблокирован.")
    except ValueError:
        await message.answer("Неверный ID.")

@dp.message(Command("unblock"))
async def cmd_unblock(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /unblock [ID]")
            return
        unblock_id = int(parts[1])
        blocked_users.pop(unblock_id, None)
        await message.answer(f"Пользователь {unblock_id} разблокирован.")
    except ValueError:
        await message.answer("Неверный ID.")

@dp.message()
async def handle_unexpected(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text or ""
    text_lower = text.lower()
    if text.startswith('/'):
        return
    if user_id in blocked_users and time.time() < blocked_users[user_id]:
        await message.answer("Вы временно заблокированы. Попробуйте позже.")
        return
    if is_rate_limited(user_id):
        await message.answer("Слишком много сообщений. Подождите 10 минут.")
        return
    if not message.text:
        await message.answer("Я работаю только с текстовыми сообщениями. Пожалуйста, напишите текстом.")
        return
    if any(word in text_lower for word in ['человек', 'менеджер', 'оператор', 'позовите', 'human', 'manager']):
        await message.answer("Конечно! Передаю ваш запрос менеджеру. Он свяжется с вами в течение 15 минут.")
        try:
            await bot.send_message(ADMIN_ID, f"🔔 Запрос менеджера!\nID: {user_id}\nUsername: @{message.from_user.username}\nСообщение: {text}")
        except Exception as e:
            logging.error(f"Не удалось уведомить админа: {e}")
        return
    profanity_words = ['мат', 'дурак', 'идиот', 'тупой', 'нахуй']

    def is_fuzzy_match(text: str, word_list: list, threshold: float = 0.75) -> bool:
        words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', text.lower())
        for word in words:
            matches = difflib.get_close_matches(word, word_list, n=1, cutoff=threshold)
            if matches:
                return True
        return False

    if any(word in text_lower for word in profanity_words):
        await message.answer("Пожалуйста, общайтесь корректно. Я здесь, чтобы помочь.")
        blocked_users[user_id] = time.time() + BLOCK_DURATION
        log_suspicious(user_id, message.from_user.username, "Оскорбление", text)
        return
    answer = find_faq_answer(text)
    thanks = ['спасибо', 'благодарю', 'спс', 'благодарствую', 'thanks', 'thank']
    farewells = ['пока', 'прощай', 'свидания', 'досвидания', 'бай', 'bye']

    if is_fuzzy_match(text, thanks):
        await message.answer("Пожалуйста! Всегда рад помочь. 😊 Если появятся вопросы — пишите.")
        return

    if is_fuzzy_match(text, farewells):
        await message.answer("До свидания! 👋 Если что - обращайтесь.")
        return

    if answer:
        await message.answer(answer)
        return
    await message.answer("Этот вопрос лучше уточнить у менеджера. Передаю вашу заявку. Он свяжется с вами.")
    try:
        await bot.send_message(ADMIN_ID, f"❓ Вопрос от пользователя!\nID: {user_id}\nUsername: @{message.from_user.username}\nВопрос: {text}")
    except Exception as e:
        logging.error(f"Не удалось уведомить админа: {e}")

@dp.errors()
async def errors_handler(event: types.ErrorEvent):
    logging.error(f"Критическая ошибка при обработке апдейта: {event.exception}")
    try:
        await bot.send_message(ADMIN_ID, f"⚠️ Ошибка в боте:\n{event.exception}")
    except Exception:
        pass
    return True

async def main():
    logging.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
