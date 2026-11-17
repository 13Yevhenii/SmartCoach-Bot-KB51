import asyncio
import gspread
import google.generativeai as genai
import os

from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Імпортуємо основні компоненти aiogram
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Завантаження налаштувань із .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Перевірка наявності ключів
if not BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError(
        "Не знайдено BOT_TOKEN або GEMINI_API_KEY у файлі .env"
    )

# БАЗА ДАНИХ (Google Sheets)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

credentials = Credentials.from_service_account_file(
    "credentials.json",
    scopes=SCOPES
)

gc = gspread.authorize(credentials)
worksheet_clients = gc.open("SmartCoach_DB").worksheet("Клієнти")

# Налаштування Gemini API
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Ти — SmartCoach, професійний фітнес-тренер.

Твої правила:
1. Відповідай лише на питання про фітнес, тренування,
   фізичну активність, відновлення та загальні принципи
   спортивного харчування.
2. Якщо питання не стосується цих тем, ввічливо поясни,
   що спеціалізуєшся лише на фітнесі та тренуваннях.
3. Відповідай українською мовою, зрозуміло та доброзичливо.
4. Надавай практичні рекомендації відповідно до рівня
   фізичної підготовки користувача.
5. Не встановлюй діагнозів і не призначай лікування.
   У разі травми або тривожних симптомів порадь звернутися
   до медичного фахівця.
6. Не рекомендуй небезпечних вправ або екстремальних дієт.
7. Відповідай лаконічно.
"""

model = genai.GenerativeModel(
    model_name="gemini-3.8-flash",
    system_instruction=SYSTEM_PROMPT
)


# Створення бота та диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Постійне меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📅 Записатись"),
            KeyboardButton(text="👤 Мій профіль")
        ],
        [
            KeyboardButton(text="🤖 Запитати тренера")
        ]
    ],
    resize_keyboard=True
)


# Стан очікування запитання
class TrainerStates(StatesGroup):
    waiting_for_question = State()


# Обробка команди /start
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    # ---ЗАПИС КОРИСТУВАЧА В БАЗУ ДАНИХ---
    user_id = str(message.from_user.id)
    first_name = message.from_user.first_name or "Без імені"
    username = f"@{message.from_user.username}" if message.from_user.username else "Немає"
    
    try:
        existing_ids = worksheet_clients.col_values(1)
        # Перевірка на дублікати: записуємо тільки якщо людини ще немає в базі
        if user_id not in existing_ids:
            worksheet_clients.append_row([user_id, first_name, username, ""])
            print(f"В базу додано нового клієнта: {first_name}")
    except Exception as e:
        print(f"Помилка запису в таблицю: {e}")
    # ------------------------------------------

    await message.answer(
        "👋 Вітаю у SmartCoach!\n\n"
        "Я ваш персональний помічник з тренувань.",
        reply_markup=main_menu
    )


# Обробка кнопки "Записатись"
@dp.message(F.text == "📅 Записатись")
async def booking_handler(message: Message):
    await message.answer("Цей розділ ще в розробці")


# Обробка кнопки "Мій профіль"
@dp.message(F.text == "👤 Мій профіль")
async def profile_handler(message: Message):
    await message.answer("Цей розділ ще в розробці")


# Обробка кнопки "Запитати тренера"
@dp.message(F.text == "🤖 Запитати тренера")
async def trainer_handler(message: Message, state: FSMContext):
    await state.set_state(TrainerStates.waiting_for_question)
    await message.answer("Напишіть ваше питання")


# Надсилання запитання до Gemini
@dp.message(TrainerStates.waiting_for_question, F.text)
async def trainer_question_handler(
    message: Message,
    state: FSMContext
):
    question = message.text.strip()

    if not question:
        await message.answer("Будь ласка, введіть ваше питання.")
        return

    if len(question) > 4000:
        await message.answer(
            "Ваше питання занадто довге. Будь ласка, скоротіть його."
        )
        return

    await message.answer("🏋️ Тренер готує відповідь...")

    try:
        response = await model.generate_content_async(question)
        answer = response.text

        if not answer:
            answer = (
                "Не вдалося сформувати відповідь. "
                "Спробуйте поставити питання інакше."
            )

        # Telegram обмежує довжину одного повідомлення
        for i in range(0, len(answer), 4000):
            await message.answer(answer[i:i + 4000])

    except Exception as error:
        print(f"Помилка Gemini API: {error}")
        await message.answer(
            "Не вдалося отримати відповідь від тренера. "
            "Спробуйте пізніше."
        )

    finally:
        await state.clear()


# Обробка нетекстових повідомлень під час очікування питання
@dp.message(TrainerStates.waiting_for_question)
async def non_text_handler(message: Message):
    await message.answer(
        "Будь ласка, напишіть ваше питання текстом."
    )


# Основна функція запуску бота
async def main():
    print("SmartCoach запущено!")
    await dp.start_polling(bot)


# Запуск програми
if __name__ == "__main__":
    asyncio.run(main())
