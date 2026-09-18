"""
utils.py — Вспомогательные функции: отправка сообщений, работа с датами.
"""

import logging
import requests
from datetime import datetime

from config import TELEGRAM_API_URL, POINTS


# ========================
# ОТПРАВКА В TELEGRAM
# ========================

def send_message(chat_id, text, reply_markup=None):
    """Отправляет текстовое сообщение в чат"""
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")


def send_photo_to_group(file_id, caption, point_key):
    """Отправляет фото в группу нужной точки"""
    try:
        group_id = POINTS[point_key].get("group_id")
        if not group_id:
            logging.error(f"Не задан group_id для точки {point_key}")
            return False
        url = f"{TELEGRAM_API_URL}/sendPhoto"
        payload = {"chat_id": group_id, "photo": file_id, "caption": caption}
        r = requests.post(url, json=payload)
        return r.status_code == 200
    except Exception as e:
        logging.error(f"Ошибка отправки фото: {e}")
        return False


def answer_callback(callback_id, text=None):
    """Ответ на callback_query (убирает 'часики' с inline-кнопки)"""
    try:
        url = f"{TELEGRAM_API_URL}/answerCallbackQuery"
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Ошибка answerCallback: {e}")


# ========================
# ДАТЫ
# ========================

def parse_short_date(text):
    """
    Парсит дату в формате ДД.ММ.ГГ (например 01.09.26).
    Возвращает datetime.date или None при ошибке.
    """
    try:
        parts = text.strip().split(".")
        if len(parts) != 3:
            return None
        day = int(parts[0])
        month = int(parts[1])
        year_short = int(parts[2])
        year = 2000 + year_short
        return datetime(year, month, day).date()
    except (ValueError, IndexError):
        return None