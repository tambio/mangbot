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

def send_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            user_name = update["message"]["from"].get("first_name", "Гость")
            
            if text == "/start":
                send_message(chat_id, "🍽 Бот учёта списаний\n\n/spisat - списать\n/report - отчёт")
            elif text == "/spisat":
                send_message(chat_id, "📝 Пример: круассан ветчина 2")
            elif text == "/report":
                send_message(chat_id, "📊 Отчёт за неделю:\nФункция в разработке")
            else:
                parts = text.rsplit(' ', 1)
                if len(parts) == 2:
                    try:
                        quantity = float(parts[1].replace(",", "."))
                        product = parts[0]
                        if save_to_sheet(user_name, product, quantity):
                            send_message(chat_id, f"✅ Списано: {product} — {quantity} шт")
                        else:
                            send_message(chat_id, "❌ Ошибка сохранения в таблицу")
                    except:
                        send_message(chat_id, "❌ Ошибка: количество должно быть числом")
                else:
                    send_message(chat_id, "❌ Формат: название количество\nПример: круассан ветчина 2")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот работает с Google Sheets!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)