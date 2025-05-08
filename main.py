from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile, Message, BufferedInputFile
from aiogram.filters import CommandStart
from flask import Flask, request
import asyncio
import threading
import os
from datetime import datetime
import socket

import time
import sqlite3

import matplotlib
from matplotlib import pyplot as plt
from dotenv import find_dotenv, load_dotenv
from menu import main_menu, stats_menu, speed_stats, stream_menu, input_menu, label_menu
from utils_graphs import create_speed_graph, set_speed_data

from aiogram.filters.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import base64
from io import BytesIO

matplotlib.use('Agg')


# Глобальный референс на главный asyncio Loop
bot_loop: asyncio.AbstractEventLoop = None

# Добавляем в начало файла
class EditLabelStates(StatesGroup):
    waiting_for_value = State()
    warning_waiting_for_value = State()
    waiting_for_type = State()
    warning_waiting_for_type = State()


load_dotenv(find_dotenv())
NGROK_DATA = os.getenv('NGROK')
bot = Bot(token=os.getenv('TOKEN'))
dp = Dispatcher()
app = Flask(__name__)

router = Router()

# Хранилище данных в памяти
count_data = {
    "total": 23,
    "type_a": 0,
    "type_b": 15,  # Демо
    "type_c": 8,  # Демо
    "defective": 0,
    "Ltype_a": 55,
    "Ltype_b": 400,  # Демо
    "Ltype_c": 29,  # Демо
}

label_photos = {
    "A": "photo/type_A.jpg",
}

# Добавляем глобальное хранилище
user_messages = {}
speed_data = []  # список кортежей (timestamp, value)
critical_threshold = 50
system_metrics = {
    "cpu": 0,
    "memory": 0,
    "gpu": 0,
    "fps": 0,
}

# Инициализация БД при старте
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()


def cleanup_old_files():
    now = time.time()
    for f in os.listdir("graphs"):
        if os.stat(os.path.join("graphs", f)).st_mtime < now - 3600:  # 1 час
            os.remove(os.path.join("graphs", f))

cleanup_old_files()

# --- SERVER ---

@app.route("/update", methods=["POST"])
def update_count():
    data = request.json

    count_data["total"] += data.get("count", 0)
    count_data["type_a"] += data.get("with_label", 0)
    count_data["Ltype_a"] -= data.get("with_label", 0)

    if(count_data["Ltype_a"] == critical_threshold):
        bot_loop.call_soon_threadsafe(bot_loop.create_task, send_label_warning("A"))

    return "ok"

@app.route("/speed", methods=["POST"])
def update_speed():
    data = request.json
    try:
        timestamp = datetime.now().isoformat(timespec="seconds")
        value = int(data.get("value", 0))
        speed_data.append((timestamp, value)) 
        from utils_graphs import speed_data_store
        speed_data_store.append((timestamp, value))
        print(f"[SPEED] Принято: {timestamp} - {value} акк/мин")
        return "ok", 200
    except Exception as e:
        print(f"Ошибка обработки /speed: {e}")
        return "error", 500

@app.route("/jam", methods=["POST"])
def jam_webhook():
    try:
        payload = request.json
        if not payload:
            return "Empty payload", 400

        img_b64 = payload.get("image_b64")
        if not img_b64:
            return "Missing image_b64", 400

        img_data = base64.b64decode(img_b64)

        bio = BytesIO(img_data)
        bio.seek(0)

        input_file = BufferedInputFile(
            bio.getvalue(), 
            filename=f"jam_{payload.get('battery_id', 'unknown')}.jpg"
        )

        text = (
            f"🚨 <b>Затор</b>\n"
            "────────────────────────\n"
            f"🕒 Время: {payload.get('timestamp', 'N/A')}\n"
            f"📷 Камера: {payload.get('camera_id', 'N/A')} (демо)"
        )

        bot_loop.call_soon_threadsafe(
            bot_loop.create_task, 
            send_jam_warning(input_file, text)
        )
        return "ok"
    
    except Exception as e:
        print(f"Ошибка в /jam: {str(e)}")
        return "Internal error", 500


@app.route("/defect", methods=["POST"])
def defect_webhook():
    try:
        payload = request.json
        if not payload:
            return "Empty payload", 400

        img_b64 = payload.get("image_b64")
        if not img_b64:
            return "Missing image_b64", 400

        img_data = base64.b64decode(img_b64)

        bio = BytesIO(img_data)
        bio.seek(0)

        input_file = BufferedInputFile(
            bio.getvalue(), 
            filename=f"jam_{payload.get('battery_id', 'unknown')}.jpg"
        )

        text = (
            f"🚨 <b>Обнаружен дефект</b> \n"
            "────────────────────────\n"
            f"🔧 Тип: {payload.get('type_defect', 'N/A')}\n"
            f"🕒 Время: {payload.get('timestamp', 'N/A')}\n"
            f"📷 Камера: {payload.get('camera_id', 'N/A')} "
        )

        bot_loop.call_soon_threadsafe(
            bot_loop.create_task, 
            send_jam_warning(input_file, text)
        )
        return "ok"
    
    except Exception as e:
        print(f"Ошибка в /defect: {str(e)}")
        return "Internal error", 500


@app.route("/metrics", methods=["POST"])
def metrics_webhook():
    data = request.json

    system_metrics['cpu'] = data.get("cpu", 0)
    system_metrics['memory'] = data.get("memory", 0)
    system_metrics['gpu'] = data.get("gpu", 0)
    system_metrics['fps'] = data.get("fps", 0)

    return "ok"

# --- SEND NOTIFICATION ---

async def send_jam_warning(photo, text):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users')
    all_users = cursor.fetchall()
    conn.close()

    for user in all_users:
        chat_id = user[0]
        try:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌", callback_data="warning_cancel")]])
            )

            if chat_id not in user_messages:
                user_messages[chat_id] = []
            user_messages[chat_id].append(message.message_id)
        except Exception as e:
            print(f"Ошибка отправки для {chat_id}: {e}")
            if "bot was blocked" in str(e).lower():
                conn = sqlite3.connect('bot.db')
                cursor = conn.cursor()
                cursor.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))
                conn.commit()
                conn.close()


async def send_label_warning(battery_type):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users')
    all_users = cursor.fetchall()
    conn.close()

    photo = FSInputFile(label_photos[battery_type])

    caption = (
        f"⚠️ Этикетки для типа *{battery_type}* заканчиваются!\n"
        f"Осталось: *{critical_threshold}* шт.\n\n"
        f"🔁 Пора менять бобину."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️", callback_data=f"warning_edit:{battery_type}"),
        InlineKeyboardButton(text="❌", callback_data="warning_cancel")
    ]])

    for user in all_users:
        chat_id = user[0]
        try:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            if chat_id not in user_messages:
                user_messages[chat_id] = []
            user_messages[chat_id].append(message.message_id)
        except Exception as e:
            print(f"Ошибка отправки для {chat_id}: {e}")
            if "bot was blocked" in str(e).lower():
                conn = sqlite3.connect('bot.db')
                cursor = conn.cursor()
                cursor.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))
                conn.commit()
                conn.close()

# --- MENU ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.delete()

    chat_id = message.chat.id
    username = message.from_user.username

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Добавляем пользователя, если его еще нет в базе
    cursor.execute('INSERT OR IGNORE INTO users (chat_id, username) VALUES (?, ?)', (chat_id, username))
    conn.commit()
    conn.close()

    await message.answer("🔋 Добро пожаловать! У нас есть почти все о чем вы могли подумуть)\n👇Выбирайте на здоровье👇:", reply_markup=main_menu)


@dp.callback_query(F.data == "stats_menu")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    message = await callback.message.edit_text("📈 Статистика (отслеживайте данные в реальном времени):", reply_markup=stats_menu)
    user_messages[user_id] = [message.message_id]


@dp.callback_query(F.data == "speed_menu")
async def speed_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await delete_previous_messages(user_id)
        
        set_speed_data(speed_data)
        img_path, _ = create_speed_graph(10)
        
        if not img_path or not speed_data:
            no_data_msg = await callback.message.answer(
                "📭 Данные о скорости пока отсутствуют",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Обновить", callback_data="speed_menu")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")]
                ])
            )
            user_messages[user_id] = [no_data_msg.message_id]
            return
            
        graph_msg = await bot.send_photo(
            chat_id=user_id,
            photo=FSInputFile(img_path),
            caption="📊 График скорости"
        )
        
        buttons_msg = await bot.send_message(
            chat_id=user_id,
            text="Выберите интервал:",
            reply_markup=speed_stats
        )
        
        user_messages[user_id] = [graph_msg.message_id, buttons_msg.message_id]
        
    except Exception as e:
        print(f"Ошибка в speed_menu: {e}")
        await callback.answer("Ошибка при отображении данных", show_alert=True)


@dp.callback_query(F.data.in_({"show_label_count", "refresh_label_count"}))
async def show_label_count(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        await delete_previous_messages(user_id)
        text = (
            "📃 Количество этикеток:\n\n"
            f"• Тип A: {count_data['Ltype_a']} шт.\n"
            f"• Тип B: {count_data['Ltype_b']} шт. (демо)\n"
            f"• Тип C: {count_data['Ltype_c']} шт. (демо)\n"
            "────────────────\n"
        )

        message = await bot.send_message(
            chat_id=user_id,
            text=text + "Обновлен: " + datetime.now().strftime("%H:%M:%S"),
            reply_markup=label_menu
        )

        user_messages[user_id] = [message.message_id]

    except Exception as e:
        print(f"Ошибка в show_label_count: {e}")
        await callback.answer("Ошибка обновления данных", show_alert=False)


@dp.callback_query(F.data.startswith("graph_"))
async def change_time_scale(callback: CallbackQuery):
    user_id = callback.from_user.id
    minutes = int(callback.data.split("_")[1])
    
    set_speed_data(speed_data)
    img_path, _ = create_speed_graph(minutes)
    
    if img_path:
        try:
            # Удаляем старый график
            await delete_previous_messages(user_id)
            
            # Отправляем новый график
            graph_msg = await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile(img_path),
                caption=f"📊 График скорости",
            )
            
            # Отправляем кнопки
            buttons_msg = await bot.send_message(
                chat_id=user_id,
                text="Выберите временной интервал:",
                reply_markup=speed_stats
            )
            
            user_messages[user_id] = [graph_msg.message_id, buttons_msg.message_id]
            
        except Exception as e:
            print(f"Ошибка при обновлении графика: {e}")
            await callback.answer("Ошибка при обновлении графика")
    else:
        await callback.answer("Нет данных для отображения")


@dp.callback_query(F.data.in_({"show_count", "refresh_count"}))
async def show_count(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        await delete_previous_messages(user_id)

        pie_path, bar_path = create_charts()
        
        text = (
            "🔋 Количество аккумуляторов:\n\n"
            f"• Тип A: {count_data['type_a']} шт.\n"
            f"• Тип B: {count_data['type_b']} шт. (демо)\n"
            f"• Тип C: {count_data['type_c']} шт. (демо)\n"
            f"• Бракованные: {count_data['defective']} шт.\n"
            "────────────────\n"
            f"📦 Всего: {count_data['total']} шт.\n"
        )
        
        media = [
            InputMediaPhoto(
                media=FSInputFile(pie_path),
                caption=text
            ),
            InputMediaPhoto(
                media=FSInputFile(bar_path)
            )
        ]
        
        media_messages = await bot.send_media_group(
            chat_id=callback.from_user.id,
            media=media
        )
        
        buttons_msg = await bot.send_message(
            chat_id=callback.from_user.id,
            text="Обновлено: " + datetime.now().strftime("%H:%M:%S"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_count")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")]
            ])
        )
        
        user_messages[user_id] = [m.message_id for m in media_messages] + [buttons_msg.message_id]            
    
    except Exception as e:
        print(f"Ошибка в show_count: {e}")
        await callback.answer("Ошибка обновления данных", show_alert=False)
    finally:
        for path in [pie_path, bar_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass


# --- BACK TO... ---

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("🔋 Добро пожаловать! У нас есть почти все о чем вы могли подумуть)\n👇Выбирайте на здоровье👇:", reply_markup=main_menu)


@dp.callback_query(F.data == "back_to_stats")
async def back_to_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        await delete_previous_messages(user_id)
        
        # Отправляем меню
        message = await bot.send_message(
            chat_id=user_id,
            text="📈 Статистика (отслеживайте данные в реальном времени):",
            reply_markup=stats_menu
        )

        user_messages[user_id] = [message.message_id]
            
    except Exception as e:
        print(f"Ошибка при возврате: {e}")
        await callback.answer("Ошибка при возврате")

# --- OTHER ---

@dp.callback_query(F.data == "download_excel")
async def send_excel(callback: CallbackQuery):
    user_id = callback.from_user.id
    set_speed_data(speed_data)
    
    last_caption = callback.message.caption if callback.message.content_type == "photo" else ""
    minutes = 10  # по умолчанию
    if "10 мин" in last_caption:
        minutes = 10
    elif "30 мин" in last_caption:
        minutes = 30
    elif "1 час" in last_caption:
        minutes = 60
    
    _, excel_path = create_speed_graph(minutes)
    
    if excel_path and os.path.exists(excel_path):
        try:
            # Отправляем файл
            doc_msg = await bot.send_document(
                chat_id=user_id,
                document=FSInputFile(excel_path),
                caption=f"📊 Данные скорости за {minutes} мин"
            )
            
            # Добавляем сообщение с файлом в историю для последующего удаления
            if user_id in user_messages:
                user_messages[user_id].append(doc_msg.message_id)
                
        except Exception as e:
            print(f"Ошибка при отправке Excel: {e}")
            await callback.answer("Ошибка при отправке файла")
    else:
        await callback.answer("Нет данных для формирования отчета")


def create_charts():
    try:
        
        labels = ['Type A', 'Type B', 'Type C', 'Брак']
        values = [count_data['type_a'], count_data['type_b'], 
                count_data['type_c'], count_data['defective']]
        
        plt.figure(figsize=(8, 8))
        plt.pie(values, autopct='%1.1f%%', startangle=90)
        plt.legend(labels, loc="best")
        plt.title('Распределение типов аккумуляторов')
        pie_path = 'stats_pie.png'
        plt.savefig(pie_path, bbox_inches='tight')
        plt.close()
        
        plt.figure(figsize=(10, 6))
        bars = plt.bar(labels, values, color=['#4CAF50', '#2196F3', '#FFC107', '#F44336'])
        plt.title('Количество по типам')
        plt.ylabel('Количество')
        
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}', ha='center', va='bottom')
        
        bar_path = 'stats_bar.png'
        plt.savefig(bar_path, bbox_inches='tight')
        plt.close()
        
        return pie_path, bar_path
        
    except Exception as e:
        print(f"Ошибка генерации графиков: {e}")
        return None, None


@dp.callback_query(F.data.startswith("warning_edit"))
async def warning_edit(callback: CallbackQuery, state: FSMContext):
    label_type = callback.data.split(":", 1)[1]
    await state.update_data(label_type=label_type)
    await callback.message.edit_caption(
        caption=f"Введите новое количество этикеток для *{label_type}*:",
        parse_mode="Markdown"
    )
    
    await state.set_state(EditLabelStates.warning_waiting_for_value)

@dp.callback_query(F.data.startswith("edit"))
async def select_label_type(callback: CallbackQuery, state: FSMContext):
    label_type = callback.data.replace("edit", "").lower()
    await state.update_data(label_type=label_type)
    
    await callback.message.edit_text(
        text=f"Введите новое количество для типа {label_type.upper()}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]
        ])
    )
    await state.set_state(EditLabelStates.waiting_for_value)

@dp.message(EditLabelStates.warning_waiting_for_value)
async def process_warning_value(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        try:
            await message.delete()
        except:
            pass

        value = int(message.text)
        if value < 0:
            raise ValueError
        

        data = await state.get_data()
        label_type = data['label_type']
        count_data[f"Ltype_{label_type.lower()}"] = value
        
        await delete_previous_messages(user_id)
        
        
        class TempCallback:
            def __init__(self):
                self.from_user = message.from_user
        
        await show_label_count(TempCallback())
        await state.clear()

    except ValueError:
        error_msg = await message.answer("Некорректное значение! Введите целое положительное число:")
        user_messages[user_id] += [error_msg.message_id]
        await state.set_state(EditLabelStates.warning_waiting_for_value)
        return

@dp.message(EditLabelStates.waiting_for_value)
async def process_label_value(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:

        try:
            await message.delete()
        except:
            pass

        value = int(message.text)
        if value < 0:
            raise ValueError
        

        data = await state.get_data()
        label_type = data['label_type']
        count_data[f"Ltype_{label_type}"] = value
        
        await delete_previous_messages(user_id)
        
        class TempCallback:
            def __init__(self):
                self.from_user = message.from_user
        
        await show_label_count(TempCallback())
        await state.clear()

    except ValueError:
        error_msg = await message.answer("Некорректное значение! Введите целое положительное число:")
        user_messages[user_id] += [error_msg.message_id]
        await state.set_state(EditLabelStates.waiting_for_value)
        return

@dp.callback_query(F.data == "cancel_edit", EditLabelStates.waiting_for_value)
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Изменение отменено")
    await show_label_count(callback)

@dp.callback_query(F.data == "warning_cancel")
async def warning_delete(callback: CallbackQuery):
    chat_id = callback.from_user.id
    await callback.message.delete()
    user_messages.get(chat_id, []).remove(callback.message.message_id)

async def delete_previous_messages(user_id: int):
    if user_id in user_messages:
        for msg_id in user_messages[user_id]:
            try:
                await bot.delete_message(user_id, msg_id)
            except Exception as e:
                print(f"Ошибка удаления сообщений: {e}")
        del user_messages[user_id]



def run_flask():
    app.run(host="0.0.0.0", port=8000)


async def main():
    global bot_loop
    bot_loop = asyncio.get_event_loop()
    threading.Thread(target=run_flask, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    
asyncio.run(main())