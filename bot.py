import os
import logging
from flask import Flask, request, jsonify
import requests
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SHEET_ID = os.environ.get("SHEET_ID")
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Хранилище временных данных пользователей
user_data = {}

def get_sheet():
    creds_path = '/etc/secrets/credentials.json'
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def save_to_sheet(user_name, product, quantity):
    try:
        sheet = get_sheet()
        now = datetime.now()
        sheet.append_row([
            now.strftime("%d.%m.%Y"),
            now.strftime("%H:%M:%S"),
            user_name,
            product,
            str(quantity)
        ])
        logging.info(f"Сохранено: {user_name} - {product} - {quantity}")
        return True
    except Exception as e:
        logging.error(f"Ошибка Google Sheets: {e}")
        return False

def send_message(chat_id, text, reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")

def send_main_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥐 Круассан", "🥪 Панини"],
            ["🥐 Слойка", "🥯 Бейгл"],
            ["🍲 Киш", "🍙 Онигири"],
            ["🌮 Кесадилья", "🌯 Тортилья"],
            ["🍰 Торт нап-мед", "🥗 Боул"],
            ["🍱 Ролл", "📊 Отчёт за неделю"],
            ["➕ Другое"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🍽 ВЫБЕРИТЕ КАТЕГОРИЮ:", reply_markup=keyboard)

# ---- КРУАССАН ----
def send_croissant_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥐 Круассан миндаль"],
            ["🥐 Круассан шоколад"],
            ["🥐 Круассан курица"],
            ["🥐 Круассан индейка"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥐 ВЫБЕРИТЕ КРУАССАН:", reply_markup=keyboard)

# ---- ПАНИНИ ----
def send_panini_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥪 Панини курица"],
            ["🥪 Панини индейка"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥪 ВЫБЕРИТЕ ПАНИНИ:", reply_markup=keyboard)

# ---- СЛОЙКА ----
def send_sloika_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥐 Слойка индейка"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥐 ВЫБЕРИТЕ СЛОЙКУ:", reply_markup=keyboard)

# ---- БЕЙГЛ ----
def send_bagel_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥯 Бейгл индейка"],
            ["🥯 Бейгл курица"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥯 ВЫБЕРИТЕ БЕЙГЛ:", reply_markup=keyboard)

# ---- БОУЛ ----
def send_bowl_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥗 Боул сёмга"],
            ["🥗 Боул курица"],
            ["🥗 Боул цезарь"],
            ["🥗 Боул фитнесс"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥗 ВЫБЕРИТЕ БОУЛ:", reply_markup=keyboard)

# ---- РОЛЛ ----
def send_roll_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🍱 Ролл курица"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🍱 ВЫБЕРИТЕ РОЛЛ:", reply_markup=keyboard)

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            user_name = update["message"]["from"].get("first_name", "Гость")
            
            # ---- КОМАНДЫ ----
            if text == "/start":
                send_main_menu(chat_id)
            
            # ---- КАТЕГОРИИ ----
            elif text == "🥐 Круассан":
                send_croissant_menu(chat_id)
            elif text == "🥪 Панини":
                send_panini_menu(chat_id)
            elif text == "🥐 Слойка":
                send_sloika_menu(chat_id)
            elif text == "🥯 Бейгл":
                send_bagel_menu(chat_id)
            elif text == "🍲 Киш":
                user_data[chat_id] = {"waiting_for": "quantity", "product": "Киш курица"}
                send_message(chat_id, "📝 Введите количество для Киш курица:")
            elif text == "🍙 Онигири":
                user_data[chat_id] = {"waiting_for": "quantity", "product": "Онигири"}
                send_message(chat_id, "📝 Введите количество для Онигири:")
            elif text == "🌮 Кесадилья":
                user_data[chat_id] = {"waiting_for": "quantity", "product": "Кесадилья"}
                send_message(chat_id, "📝 Введите количество для Кесадилья:")
            elif text == "🌯 Тортилья":
                user_data[chat_id] = {"waiting_for": "quantity", "product": "Тортилья"}
                send_message(chat_id, "📝 Введите количество для Тортилья:")
            elif text == "🍰 Торт нап-мед":
                user_data[chat_id] = {"waiting_for": "quantity", "product": "Торт нап-мед"}
                send_message(chat_id, "📝 Введите количество для Торт нап-мед:")
            elif text == "🥗 Боул":
                send_bowl_menu(chat_id)
            elif text == "🍱 Ролл":
                send_roll_menu(chat_id)
            elif text == "📊 Отчёт за неделю":
                send_message(chat_id, "📊 Функция отчёта скоро будет готова!")
            elif text == "➕ Другое":
                user_data[chat_id] = {"waiting_for": "other_product"}
                send_message(chat_id, "✏️ Напишите название позиции:")
            elif text == "◀️ Назад":
                send_main_menu(chat_id)
            
            # ---- КРУАССАНЫ ----
            elif text in ["🥐 Круассан миндаль", "🥐 Круассан шоколад", "🥐 Круассан курица", "🥐 Круассан индейка"]:
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- ПАНИНИ ----
            elif text in ["🥪 Панини курица", "🥪 Панини индейка"]:
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- СЛОЙКА ----
            elif text == "🥐 Слойка индейка":
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- БЕЙГЛ ----
            elif text in ["🥯 Бейгл индейка", "🥯 Бейгл курица"]:
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- БОУЛЫ ----
            elif text in ["🥗 Боул сёмга", "🥗 Боул курица", "🥗 Боул цезарь", "🥗 Боул фитнесс"]:
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- РОЛЛ ----
            elif text == "🍱 Ролл курица":
                user_data[chat_id] = {"waiting_for": "quantity", "product": text}
                send_message(chat_id, f"📝 Введите количество для {text}:")
            
            # ---- ОБРАБОТКА КОЛИЧЕСТВА ----
            elif chat_id in user_data and user_data[chat_id].get("waiting_for") == "quantity":
                try:
                    quantity = float(text.replace(",", "."))
                    product = user_data[chat_id]["product"]
                    if save_to_sheet(user_name, product, quantity):
                        send_message(chat_id, f"✅ Списано: {product} — {quantity} шт")
                    else:
                        send_message(chat_id, "❌ Ошибка сохранения в таблицу")
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ Введите число, например: 2 или 1.5")
            
            # ---- РУЧНОЙ ВВОД (Другое) ----
            elif chat_id in user_data and user_data[chat_id].get("waiting_for") == "other_product":
                product = text
                user_data[chat_id] = {"waiting_for": "quantity_other", "product": product}
                send_message(chat_id, f"📝 Введите количество для {product}:")
            
            elif chat_id in user_data and user_data[chat_id].get("waiting_for") == "quantity_other":
                try:
                    quantity = float(text.replace(",", "."))
                    product = user_data[chat_id]["product"]
                    if save_to_sheet(user_name, product, quantity):
                        send_message(chat_id, f"✅ Списано: {product} — {quantity} шт")
                    else:
                        send_message(chat_id, "❌ Ошибка сохранения в таблицу")
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ Введите количество числом!")
            
            else:
                send_message(chat_id, "❌ Используйте кнопки меню")
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот работает!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)