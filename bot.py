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

# ========================
# РАБОТА С GOOGLE SHEETS
# ========================

def get_sheet():
    """Подключение к Google Sheets"""
    creds_path = '/etc/secrets/credentials.json'
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def get_all_funds():
    """Получить все фонды из таблицы"""
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()
        if len(data) <= 1:
            return []
        # Пропускаем заголовок, берём только название фонда (колонка 0)
        funds = [row[0] for row in data[1:] if len(row) > 0 and row[0].strip()]
        return funds
    except Exception as e:
        logging.error(f"Ошибка получения фондов: {e}")
        return []

def add_fund(fund_name, rating):
    """Добавить новый фонд с оценкой"""
    try:
        sheet = get_sheet()
        now = datetime.now()
        sheet.append_row([
            fund_name,
            rating,
            now.strftime("%d.%m.%Y %H:%M:%S"),
            "Активен"
        ])
        logging.info(f"Добавлен фонд: {fund_name} с оценкой {rating}")
        return True
    except Exception as e:
        logging.error(f"Ошибка добавления фонда: {e}")
        return False

def delete_fund(fund_name):
    """Удалить фонд по названию"""
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()
        for i, row in enumerate(data):
            if len(row) > 0 and row[0] == fund_name:
                sheet.delete_rows(i + 1)  # +1 потому что индексация с 1
                logging.info(f"Удалён фонд: {fund_name}")
                return True
        return False
    except Exception as e:
        logging.error(f"Ошибка удаления фонда: {e}")
        return False

def get_all_ratings():
    """Получить все оценки по фондам"""
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()
        if len(data) <= 1:
            return []
        # Пропускаем заголовок
        ratings = []
        for row in data[1:]:
            if len(row) >= 2 and row[0].strip():
                ratings.append({
                    'name': row[0],
                    'rating': row[1] if len(row) > 1 else 'Нет оценки',
                    'date': row[2] if len(row) > 2 else 'Нет даты',
                    'status': row[3] if len(row) > 3 else 'Активен'
                })
        return ratings
    except Exception as e:
        logging.error(f"Ошибка получения оценок: {e}")
        return []

# ========================
# ОТПРАВКА СООБЩЕНИЙ
# ========================

def send_message(chat_id, text, reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")

def send_main_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["➕ Добавить фонд"],
            ["❌ Удалить фонд"],
            ["📋 Шорт-лист"],
            ["⭐ Посмотреть оценки"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🏦 УПРАВЛЕНИЕ ФОНДАМИ\n\nВыберите действие:", reply_markup=keyboard)

# ========================
# ОСНОВНОЙ WEBHOOK
# ========================

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            user_name = update["message"]["from"].get("first_name", "Гость")
            
            # ---- КОМАНДА START ----
            if text == "/start":
                send_main_menu(chat_id)
            
            # ---- ДОБАВИТЬ ФОНД ----
            elif text == "➕ Добавить фонд":
                user_data[chat_id] = {"step": "add_fund_name"}
                send_message(chat_id, "📝 Введите НАЗВАНИЕ фонда:")
            
            elif chat_id in user_data and user_data[chat_id].get("step") == "add_fund_name":
                fund_name = text.strip()
                user_data[chat_id] = {"step": "add_fund_rating", "fund_name": fund_name}
                send_message(chat_id, f"📊 Введите ОЦЕНКУ для {fund_name} (число от 1 до 10):")
            
            elif chat_id in user_data and user_data[chat_id].get("step") == "add_fund_rating":
                try:
                    rating = float(text.replace(",", "."))
                    fund_name = user_data[chat_id]["fund_name"]
                    
                    if add_fund(fund_name, rating):
                        send_message(chat_id, f"✅ Фонд <b>{fund_name}</b> добавлен с оценкой {rating}")
                    else:
                        send_message(chat_id, "❌ Ошибка добавления фонда")
                    
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ Оценка должна быть числом. Попробуйте ещё раз:")
            
            # ---- УДАЛИТЬ ФОНД ----
            elif text == "❌ Удалить фонд":
                funds = get_all_funds()
                if not funds:
                    send_message(chat_id, "📭 Нет активных фондов для удаления")
                    send_main_menu(chat_id)
                    return
                
                # Создаём клавиатуру со списком фондов
                keyboard = {"keyboard": [[fund] for fund in funds] + [["◀️ Назад"]], "resize_keyboard": True}
                send_message(chat_id, "❌ Выберите фонд для удаления:", reply_markup=keyboard)
                user_data[chat_id] = {"step": "delete_fund_select"}
            
            elif chat_id in user_data and user_data[chat_id].get("step") == "delete_fund_select":
                if text == "◀️ Назад":
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                    return
                
                fund_name = text.strip()
                if delete_fund(fund_name):
                    send_message(chat_id, f"✅ Фонд <b>{fund_name}</b> удалён")
                else:
                    send_message(chat_id, f"❌ Фонд <b>{fund_name}</b> не найден")
                
                del user_data[chat_id]
                send_main_menu(chat_id)
            
            # ---- ШОРТ-ЛИСТ ----
            elif text == "📋 Шорт-лист":
                funds = get_all_funds()
                if not funds:
                    send_message(chat_id, "📭 Фонды не найдены")
                else:
                    # Формируем красивый список с номерами
                    short_list = "📋 <b>ШОРТ-ЛИСТ ФОНДОВ</b>\n\n"
                    for i, fund in enumerate(funds, 1):
                        short_list += f"{i}. {fund}\n"
                    send_message(chat_id, short_list)
                send_main_menu(chat_id)
            
            # ---- ПОСМОТРЕТЬ ОЦЕНКИ ----
            elif text == "⭐ Посмотреть оценки":
                ratings = get_all_ratings()
                if not ratings:
                    send_message(chat_id, "📭 Оценки не найдены")
                else:
                    # Формируем таблицу с оценками
                    rating_list = "⭐ <b>ОЦЕНКИ ФОНДОВ</b>\n\n"
                    for item in ratings:
                        rating_list += f"📌 {item['name']}\n"
                        rating_list += f"   Оценка: <b>{item['rating']}</b>\n"
                        rating_list += f"   Дата: {item['date']}\n"
                        rating_list += f"   Статус: {item['status']}\n\n"
                    send_message(chat_id, rating_list)
                send_main_menu(chat_id)
            
            # ---- НАЗАД ----
            elif text == "◀️ Назад":
                if chat_id in user_data:
                    del user_data[chat_id]
                send_main_menu(chat_id)
            
            else:
                send_message(chat_id, "❌ Используйте кнопки меню")
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот управления фондами работает!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)