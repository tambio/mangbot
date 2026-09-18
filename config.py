"""
Все настройки и константы бота.
"""

import os
from zoneinfo import ZoneInfo

# ========================
# TELEGRAM
# ========================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# ========================
# GOOGLE SHEETS
# ========================

SHEET_ID = os.environ.get("SHEET_ID")
SHEET_ID_2 = os.environ.get("SHEET_ID_2")

# ========================
# ГРУППЫ
# ========================

GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")
GROUP_CHAT_ID_2 = os.environ.get("GROUP_CHAT_ID_2")

# ========================
# ТОЧКИ
# ========================

POINTS = {
    "point_1": {
        "name": os.environ.get("POINT_1_NAME", "Мангелик"),
        "sheet_id": SHEET_ID,
        "group_id": GROUP_CHAT_ID
    },
    "point_2": {
        "name": os.environ.get("POINT_2_NAME", "МФЦА"),
        "sheet_id": SHEET_ID_2,
        "group_id": GROUP_CHAT_ID_2
    }
}

# Привязка группы → точки
GROUP_TO_POINT = {
    str(GROUP_CHAT_ID): "point_1",
    str(GROUP_CHAT_ID_2): "point_2"
}

# ========================
# ВРЕМЯ И МЕСЯЦЫ
# ========================

TIMEZONE = ZoneInfo("Asia/Almaty")

MONTHS = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
]

# ========================
# TELEGRAM API
# ========================

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ========================
# ХРАНИЛИЩА СОСТОЯНИЙ
# ========================

# Временные состояния пользователей (ожидание ввода)
user_data = {}

# Выбранная точка для каждого пользователя (в личке)
user_points = {}