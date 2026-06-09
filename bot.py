import os
import json
import logging
from flask import Flask, request, jsonify
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
app = Flask(__name__)

# Включаем логирование для отладки
logging.basicConfig(level=logging.INFO)

# URL для отправки сообщений в Telegram
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_message(chat_id, text):
    """Отправляет сообщение пользователю"""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, json=data)
        logging.info(f"Сообщение отправлено: {response.status_code}")
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    """Точка входа для сообщений от Telegram"""
    try:
        # Получаем данные от Telegram
        update = request.get_json()
        logging.info(f"Получено обновление: {update}")
        
        # Извлекаем информацию о сообщении
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            user_name = update["message"]["from"].get("first_name", "Гость")
            
            # Обработка команды /start
            if text == "/start":
                send_message(chat_id, f"🍽 Привет, {user_name}!\n\nЯ бот для учета списаний в кофейне.\n\nДоступные команды:\n/spisat - списать позицию\n/report - отчет за неделю")
            
            elif text == "/spisat":
                send_message(chat_id, "🥐 Выберите позицию:\n\nОтправьте число (например, 5), чтобы списать круассаны.\nСкоро добавлю кнопки с меню!")
            
            elif text == "/report":
                send_message(chat_id, "📊 Отчет за неделю:\nПока пусто. После списаний здесь будут данные.")
            
            else:
                # Пробуем распознать число как списание
                try:
                    quantity = float(text.replace(",", "."))
                    send_message(chat_id, f"✅ Списано: {quantity} шт.\n\nСпасибо! Используйте /spisat для нового списания.")
                except:
                    send_message(chat_id, "❌ Неизвестная команда.\n\nИспользуйте /start для начала работы.")
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Ошибка в вебхуке: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    """Проверка, что сервер работает"""
    return "Бот работает! Версия 2.0", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)