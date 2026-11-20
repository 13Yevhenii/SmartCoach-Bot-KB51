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

# Підключення до Google Sheets
spreadsheet = gc.open("SmartCoach_DB")

# Отримання доступу до аркушів
worksheet_clients = spreadsheet.worksheet("Клієнти")
worksheet_schedule = spreadsheet.worksheet("Розклад")

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

# Клавіатура для вибору дати тренування
def create_date_keyboard(dates):
    keyboard = []

    for date in dates:
        keyboard.append([KeyboardButton(text=date)])

    keyboard.append([KeyboardButton(text="⬅️ Назад")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )

class TrainerStates(StatesGroup):
    waiting_for_question = State()

# Стани процесу бронювання
class BookingStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_confirmation = State()
    waiting_for_cancellation = State()

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
        else:
           client_row = existing_ids.index(user_id) + 1

           worksheet_clients.update_cell(client_row, 2, first_name)
           worksheet_clients.update_cell(client_row, 3, username)

           print(f"Дані клієнта оновлено: {first_name}")
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
async def booking_handler(message: Message, state: FSMContext):
    await state.clear()

    try:
        rows = worksheet_schedule.get_all_records()

        # Отримуємо унікальні дати з вільними слотами
        available_dates = sorted({
            str(row["Дата"])
            for row in rows
            if str(row["Статус (вільно/зайнято)"]).strip().lower() == "вільно"
        })

        if not available_dates:
            await message.answer("На жаль, вільних дат для тренування немає.")
            return

        await state.set_state(BookingStates.waiting_for_date)

        await message.answer(
            "📅 Оберіть дату тренування:",
            reply_markup=create_date_keyboard(available_dates)
        )

    except Exception as e:
        print(f"Помилка отримання розкладу: {e}")
        await message.answer("Не вдалося завантажити розклад. Спробуйте пізніше.")

# Повернення до головного меню під час бронювання
@dp.message(F.text == "⬅️ Назад")
async def booking_back_handler(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Ви повернулися до головного меню.",
        reply_markup=main_menu
    )

# Клавіатура для вибору часу тренування
def create_time_keyboard(times):
    keyboard = []

    for time in times:
        keyboard.append([KeyboardButton(text=time)])

    keyboard.append([KeyboardButton(text="⬅️ До вибору дати")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )

# Обробка вибору дати тренування
@dp.message(BookingStates.waiting_for_date, F.text)
async def select_booking_date_handler(
    message: Message,
    state: FSMContext
):
    selected_date = message.text.strip()

    try:
        # Отримуємо записи з Google Sheets
        rows = worksheet_schedule.get_all_records()

        # Знаходимо вільний час для вибраної дати
        available_times = sorted({
            str(row["Час"]).strip()
            for row in rows
            if str(row["Дата"]).strip() == selected_date
            and str(row["Статус (вільно/зайнято)"]).strip().lower() == "вільно"
        })

        if not available_times:
            await message.answer(
                "На цю дату немає вільного часу. Оберіть іншу дату.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        # Зберігаємо вибрану дату
        await state.update_data(selected_date=selected_date)

        # Переходимо до вибору часу
        await state.set_state(BookingStates.waiting_for_time)

        await message.answer(
            f"📅 Обрана дата: {selected_date}\n\n"
            "🕒 Оберіть зручний час тренування:",
            reply_markup=create_time_keyboard(available_times)
        )

    except Exception as e:
        print(f"Помилка вибору дати: {e}")
        await message.answer(
            "Не вдалося завантажити доступний час. Спробуйте пізніше.",
            reply_markup=main_menu
        )
        await state.clear()

# Повернення до вибору дати
@dp.message(
    BookingStates.waiting_for_time,
    F.text == "⬅️ До вибору дати"
)
async def back_to_date_handler(
    message: Message,
    state: FSMContext
):
    await state.set_state(BookingStates.waiting_for_date)

    try:
        rows = worksheet_schedule.get_all_records()

        available_dates = sorted({
            str(row["Дата"]).strip()
            for row in rows
            if str(row["Статус (вільно/зайнято)"]).strip().lower() == "вільно"
        })

        await message.answer(
            "📅 Оберіть дату тренування:",
            reply_markup=create_date_keyboard(available_dates)
        )

    except Exception as e:
        print(f"Помилка отримання дат: {e}")
        await message.answer(
            "Не вдалося завантажити дати.",
            reply_markup=main_menu
        )
        await state.clear()

# Обробка вибору часу тренування
@dp.message(BookingStates.waiting_for_time, F.text)
async def select_booking_time_handler(
    message: Message,
    state: FSMContext
):
    selected_time = message.text.strip()

    if selected_time == "⬅️ До вибору дати":
        return

    try:
        booking_data = await state.get_data()
        selected_date = booking_data.get("selected_date")

        if not selected_date:
            await message.answer(
                "Не вдалося визначити дату. Почніть запис заново.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        rows = worksheet_schedule.get_all_records()

        # Перевіряємо, чи вибраний час досі вільний
        slot_exists = any(
            str(row["Дата"]).strip() == selected_date
            and str(row["Час"]).strip() == selected_time
            and str(row["Статус (вільно/зайнято)"]).strip().lower() == "вільно"
            for row in rows
        )

        if not slot_exists:
            await message.answer(
                "На жаль, цей час уже недоступний. "
                "Оберіть інший час.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        await state.update_data(selected_time=selected_time)
        await state.set_state(BookingStates.waiting_for_confirmation)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="✅ Підтвердити запис"),
                    KeyboardButton(text="❌ Скасувати")
                ]
            ],
            resize_keyboard=True
        )

        await message.answer(
            f"📅 Дата: {selected_date}\n"
            f"🕒 Час: {selected_time}\n\n"
            "Підтверджуєте запис на тренування?",
            reply_markup=keyboard
        )

    except Exception as e:
        print(f"Помилка вибору часу: {e}")
        await message.answer(
            "Не вдалося обробити вибір часу. Спробуйте пізніше.",
            reply_markup=main_menu
        )
        await state.clear()

# Підтвердження бронювання тренування
@dp.message(
    BookingStates.waiting_for_confirmation,
    F.text == "✅ Підтвердити запис"
)
async def confirm_booking_handler(
    message: Message,
    state: FSMContext
):
    try:
        booking_data = await state.get_data()

        selected_date = booking_data.get("selected_date")
        selected_time = booking_data.get("selected_time")

        if not selected_date or not selected_time:
            await message.answer(
                "Не вдалося отримати дані бронювання. Спробуйте ще раз.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        # Повторна перевірка доступності слота
        rows = worksheet_schedule.get_all_values()

        for row_number, row in enumerate(rows[1:], start=2):
            if (
                len(row) >= 4
                and row[0].strip() == selected_date
                and row[1].strip() == selected_time
            ):
                if row[2].strip().lower() != "вільно":
                    await message.answer(
                        "На жаль, цей час уже зайнятий. "
                        "Оберіть інший слот.",
                        reply_markup=main_menu
                    )
                    await state.clear()
                    return

                # Отримуємо ім'я клієнта
                first_name = message.from_user.first_name or "Клієнт"

                # Отримуємо Telegram ID користувача
                user_id = str(message.from_user.id)

                # Зберігаємо інформацію про бронювання
                worksheet_schedule.update_cell(row_number, 3, "зайнято")
                worksheet_schedule.update_cell(row_number, 4, first_name)
                worksheet_schedule.update_cell(row_number, 5, user_id)

                await message.answer(
                    "✅ Ви успішно записалися на тренування!\n\n"
                    f"📅 Дата: {selected_date}\n"
                    f"🕒 Час: {selected_time}\n"
                    f"👤 Клієнт: {first_name}",
                    reply_markup=main_menu
                )

                await state.clear()
                return

        await message.answer(
            "Обраний час не знайдено в розкладі. "
            "Спробуйте записатися ще раз.",
            reply_markup=main_menu
        )
        await state.clear()

    except Exception as e:
        print(f"Помилка підтвердження бронювання: {e}")
        await message.answer(
            "Не вдалося зберегти бронювання. Спробуйте пізніше.",
            reply_markup=main_menu
        )
        await state.clear()

# Скасування підтвердження бронювання
@dp.message(
    BookingStates.waiting_for_confirmation,
    F.text == "❌ Скасувати"
)
async def cancel_confirmation_handler(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "Бронювання скасовано. Ви повернулися до головного меню.",
        reply_markup=main_menu
    )


# Обробка кнопки "Мій профіль"
@dp.message(F.text == "👤 Мій профіль")
async def profile_handler(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)

    try:
        # Отримуємо інформацію про користувача
        client_ids = worksheet_clients.col_values(1)

        if user_id not in client_ids:
            await message.answer(
                "Ваш профіль не знайдено. Натисніть /start для реєстрації.",
                reply_markup=main_menu
            )
            return

        # Знаходимо користувача в таблиці клієнтів
        client_row = client_ids.index(user_id) + 1
        client_data = worksheet_clients.row_values(client_row)

        first_name = client_data[1] if len(client_data) > 1 else "Не вказано"
        username = client_data[2] if len(client_data) > 2 else "Немає"

        # Шукаємо активне бронювання за Telegram ID
        schedule_rows = worksheet_schedule.get_all_values()
        active_booking = None

        for row_number, row in enumerate(schedule_rows[1:], start=2):
            if len(row) >= 5:
                booking_date = row[0].strip()
                booking_time = row[1].strip()
                booking_status = row[2].strip().lower()
                booking_client = row[3].strip()
                booking_user_id = row[4].strip()

                if (
                    booking_status == "зайнято"
                    and booking_user_id == user_id
                ):
                    active_booking = {
                        "row_number": row_number,
                        "date": booking_date,
                        "time": booking_time,
                        "client": booking_client
                    }
                    break

        profile_text = (
            "👤 Ваш профіль SmartCoach\n\n"
            f"Ім'я: {first_name}\n"
            f"Telegram: {username}\n"
        )

        if active_booking:
            # Зберігаємо дані бронювання для подальшого скасування
            await state.update_data(
                booking_row=active_booking["row_number"],
                booking_date=active_booking["date"],
                booking_time=active_booking["time"],
                booking_client=active_booking["client"],
                booking_user_id=user_id
            )

            await state.set_state(BookingStates.waiting_for_cancellation)

            profile_text += (
                "\n📅 Ваше активне бронювання:\n"
                f"Дата: {active_booking['date']}\n"
                f"Час: {active_booking['time']}\n\n"
                "За потреби ви можете скасувати запис."
            )

            profile_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="❌ Скасувати запис")],
                    [KeyboardButton(text="⬅️ Назад")]
                ],
                resize_keyboard=True
            )

            await message.answer(
                profile_text,
                reply_markup=profile_keyboard
            )

        else:
            await state.clear()

            profile_text += "\n📅 Активних бронювань немає."

            await message.answer(
                profile_text,
                reply_markup=main_menu
            )

    except Exception as e:
        print(f"Помилка відкриття профілю: {e}")

        await state.clear()

        await message.answer(
            "Не вдалося завантажити профіль. Спробуйте пізніше.",
            reply_markup=main_menu
        )


# Скасування активного бронювання
@dp.message(
    BookingStates.waiting_for_cancellation,
    F.text == "❌ Скасувати запис"
)
async def cancel_booking_handler(
    message: Message,
    state: FSMContext
):
    try:
        booking_data = await state.get_data()

        row_number = booking_data.get("booking_row")
        booking_date = booking_data.get("booking_date")
        booking_time = booking_data.get("booking_time")
        booking_client = booking_data.get("booking_client")
        booking_user_id = booking_data.get("booking_user_id")

        current_user_id = str(message.from_user.id)

        if (
            not all([row_number, booking_date, booking_time, booking_client])
            or booking_user_id != current_user_id
        ):
            await message.answer(
                "Не вдалося отримати дані бронювання.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        # Повторно перевіряємо дані слота перед скасуванням
        current_row = worksheet_schedule.row_values(row_number)

        if (
            len(current_row) < 5
            or current_row[0].strip() != booking_date
            or current_row[1].strip() != booking_time
            or current_row[2].strip().lower() != "зайнято"
            or current_row[3].strip() != booking_client
            or current_row[4].strip() != current_user_id
        ):
            await message.answer(
                "Це бронювання вже змінено або скасовано.",
                reply_markup=main_menu
            )
            await state.clear()
            return

        # Звільняємо часовий слот у Google Sheets
        worksheet_schedule.update_cell(row_number, 3, "вільно")
        worksheet_schedule.update_cell(row_number, 4, "")
        worksheet_schedule.update_cell(row_number, 5, "")

        await state.clear()

        await message.answer(
            "✅ Ваш запис успішно скасовано!\n\n"
            f"📅 Дата: {booking_date}\n"
            f"🕒 Час: {booking_time}\n\n"
            "Цей час знову доступний для бронювання.",
            reply_markup=main_menu
        )

    except Exception as e:
        print(f"Помилка скасування бронювання: {e}")

        await message.answer(
            "Не вдалося скасувати запис. Спробуйте пізніше.",
            reply_markup=main_menu
        )
        await state.clear()

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
