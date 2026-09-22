# Telegram-бот для записи клиентов 🦷

Бот для стоматологии «33 зуба», который собирает заявки, валидирует данные и сохраняет их в Google Sheets.

## Функционал
- Пошаговый сбор данных (имя, телефон, удобное время)
- Валидация ввода (имя, телефон, время)
- Защита от спама, мата и повторных заявок
- Логирование подозрительной активности
- Админ-панель: /admin, /export, /block, /unblock

## Стек
- Python 3.11
- aiogram 3.x
- gspread, google-auth
- openpyxl
- python-dotenv

## Установка
1. Клонировать репозиторий
2. Создать виртуальное окружение: `python -m venv .venv`
3. Активировать: `.venv\Scripts\activate`
4. Установить зависимости: `pip install -r requirements.txt`
5. Создать `.env` по образцу `.env.example`
6. Положить `credentials.json` от Google Service Account
7. Запустить: `python main.py`

## Автор
Levchenko Ivan — @Wh1teNightMare
