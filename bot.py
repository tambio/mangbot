import os
import logging
from flask import Flask, request, jsonify
import requests
from datetime import datetime, timedelta
import calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import (
    TELEGRAM_TOKEN,
    POINTS,
    GROUP_TO_POINT,
    TIMEZONE,
    MONTHS,
    user_data,
    user_points,
)
from utils import (
    send_message,
    send_photo_to_group,
    answer_callback,
    parse_short_date,
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ========================
# GOOGLE SHEETS
# ========================

def get_sheet(sheet_name, point_key=None):
    creds_path = '/etc/secrets/credentials.json'
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    if point_key is None:
        raise ValueError("point_key обязателен")
    sheet_id = POINTS[point_key]["sheet_id"]
    return client.open_by_key(sheet_id).worksheet(sheet_name)

def get_menu(point_key):
    try:
        sheet = get_sheet("Прайс", point_key)
        data = sheet.get_all_values()
        menu = {}
        for row in data[1:]:
            if len(row) >= 3 and row[0].strip() and row[1].strip():
                cat = row[0].strip()
                name = row[1].strip()
                try:
                    price = float(row[2])
                except:
                    price = 0
                menu.setdefault(cat, []).append((name, price))
        return menu
    except Exception as e:
        logging.error(f"Ошибка чтения меню: {e}")
        return {}

def get_price(product_name, point_key):
    menu = get_menu(point_key)
    for cat, items in menu.items():
        for name, price in items:
            if name == product_name:
                return price
    return 0

def save_to_sheet(user_name, product, quantity, point_key):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        price = get_price(product, point_key)
        loss = price * quantity
        now = datetime.now(TIMEZONE)
        sheet.append_row([
            now.strftime("%d.%m.%Y"),
            now.strftime("%H:%M:%S"),
            user_name,
            product,
            str(quantity),
            str(price),
            str(loss)
        ])
        return True, loss
    except Exception as e:
        logging.error(f"Ошибка Google Sheets: {e}")
        return False, 0

# ========================
# МЕНЮ
# ========================

def send_point_selection(chat_id):
    keyboard = {
        "keyboard": [
            [f"🏠 {POINTS['point_1']['name']}", f"🏠 {POINTS['point_2']['name']}"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }
    send_message(chat_id, "🏪 ВЫБЕРИТЕ ТОЧКУ:", reply_markup=keyboard)

def send_main_menu(chat_id, point_key):
    menu = get_menu(point_key)
    categories = list(menu.keys())
    keyboard = []
    row = []
    for cat in categories:
        row.append(cat)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(["📊 Отчёты", "📸 Обстановка на точке"])
    keyboard.append(["➕ Другое", "🏪 Сменить точку"])
    keyboard_obj = {"keyboard": keyboard, "resize_keyboard": True}
    point_name = POINTS[point_key]["name"]
    send_message(chat_id, f"📍 Точка: {point_name}\n🍽 Выберите категорию:", reply_markup=keyboard_obj)

def send_category_menu(chat_id, category, point_key):
    menu = get_menu(point_key)
    items = menu.get(category, [])
    if not items:
        send_message(chat_id, f"❌ В категории «{category}» нет товаров")
        send_main_menu(chat_id, point_key)
        return
    keyboard = [[name] for name, price in items]
    keyboard.append(["◀️ Назад"])
    send_message(chat_id, f"📦 {category}:", reply_markup={"keyboard": keyboard, "resize_keyboard": True})

def send_reports_menu(chat_id, point_key):
    keyboard = {"keyboard": [
        ["📆 За текущую неделю"],
        ["📅 За месяц"],
        ["📊 За период"],
        ["◀️ Назад"]
    ], "resize_keyboard": True}
    send_message(chat_id, "📊 ВЫБЕРИТЕ ТИП ОТЧЁТА:", reply_markup=keyboard)

def send_month_selection(chat_id):
    months_kb = []
    row = []
    for i, month in enumerate(MONTHS):
        row.append(month)
        if len(row) == 3 or i == len(MONTHS) - 1:
            months_kb.append(row.copy())
            row = []
    months_kb.append(["◀️ Назад"])
    send_message(chat_id, "🗓 ВЫБЕРИТЕ МЕСЯЦ:", reply_markup={"keyboard": months_kb, "resize_keyboard": True})

def send_week_selection(chat_id, month_name, year):
    month_num = MONTHS.index(month_name) + 1
    last_day = calendar.monthrange(year, month_num)[1]
    weeks = []
    ws = 1
    while ws <= last_day:
        we = min(ws + 6, last_day)
        weeks.append((ws, we))
        ws += 7
    keyboard = []
    for ws, we in weeks:
        keyboard.append([f"{ws}-{we} {month_name}" if ws != we else f"{ws} {month_name}"])
    keyboard.append(["Весь месяц", "◀️ Назад"])
    send_message(chat_id, f"🗓 {month_name.upper()} {year} — выберите неделю:", reply_markup={"keyboard": keyboard, "resize_keyboard": True})

# ========================
# ОТЧЁТЫ (личка — с ценами)
# ========================

def send_weekly_report(chat_id, point_key):
    report = build_week_report_text(point_key, hide_prices=False)
    if report:
        send_message(chat_id, report)
    else:
        send_message(chat_id, "📭 За неделю списаний нет")

def send_monthly_report(chat_id, month_name, year, point_key, week_range=None):
    report = build_month_by_name_text(point_key, month_name, year, week_range, hide_prices=False)
    if report:
        send_message(chat_id, report)
    else:
        send_message(chat_id, "📭 За указанный период списаний нет")

def send_period_report(chat_id, point_key, date_from, date_to):
    report = build_period_report_text(point_key, date_from, date_to, hide_prices=False)
    if report:
        send_message(chat_id, report)
    else:
        send_message(chat_id, "📭 За этот период списаний нет")

# ========================
# ОБЩИЕ ФУНКЦИИ ФОРМИРОВАНИЯ ОТЧЁТОВ
# ========================

def build_week_report_text(point_key, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1:
            return None
        week_ago = datetime.now(TIMEZONE) - timedelta(days=7)
        stats = {}
        for row in data[1:]:
            if len(row) >= 7:
                try:
                    row_date = datetime.strptime(row[0], "%d.%m.%Y")
                    if row_date.date() >= week_ago.date():
                        product = row[3]
                        qty = float(row[4])
                        loss = float(row[6])
                        stats.setdefault(product, {"qty": 0, "loss": 0})
                        stats[product]["qty"] += qty
                        stats[product]["loss"] += loss
                except:
                    continue
        if not stats:
            return None
        point_name = POINTS[point_key]["name"]
        report = f"📊 ОТЧЁТ ЗА НЕДЕЛЮ ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices:
                report += f"{product}: {d['qty']:.0f} шт\n"
            else:
                report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        return report
    except Exception as e:
        logging.error(f"Ошибка недельного отчёта: {e}")
        return None

def build_month_report_text(point_key, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1:
            return None
        now = datetime.now(TIMEZONE)
        stats = {}
        for row in data[1:]:
            if len(row) >= 7:
                try:
                    row_date = datetime.strptime(row[0], "%d.%m.%Y")
                    if row_date.year == now.year and row_date.month == now.month:
                        product = row[3]
                        qty = float(row[4])
                        loss = float(row[6])
                        stats.setdefault(product, {"qty": 0, "loss": 0})
                        stats[product]["qty"] += qty
                        stats[product]["loss"] += loss
                except:
                    continue
        if not stats:
            return None
        point_name = POINTS[point_key]["name"]
        month_name = MONTHS[now.month - 1]
        report = f"📊 ОТЧЁТ ЗА {month_name} {now.year} ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices:
                report += f"{product}: {d['qty']:.0f} шт\n"
            else:
                report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        return report
    except Exception as e:
        logging.error(f"Ошибка месячного отчёта: {e}")
        return None

def build_month_by_name_text(point_key, month_name, year, week_range=None, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1:
            return None
        month_num = MONTHS.index(month_name) + 1
        stats = {}
        for row in data[1:]:
            if len(row) >= 7:
                try:
                    row_date = datetime.strptime(row[0], "%d.%m.%Y")
                    if row_date.year == year and row_date.month == month_num:
                        if week_range and not (week_range[0] <= row_date.day <= week_range[1]):
                            continue
                        product = row[3]
                        qty = float(row[4])
                        loss = float(row[6])
                        stats.setdefault(product, {"qty": 0, "loss": 0})
                        stats[product]["qty"] += qty
                        stats[product]["loss"] += loss
                except:
                    continue
        if not stats:
            return None
        point_name = POINTS[point_key]["name"]
        if week_range:
            report = f"📊 ОТЧЁТ ЗА {week_range[0]}-{week_range[1]} {month_name} ({point_name})\n\n"
        else:
            report = f"📊 ОТЧЁТ ЗА {month_name} {year} ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices:
                report += f"{product}: {d['qty']:.0f} шт\n"
            else:
                report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        return report
    except Exception as e:
        logging.error(f"Ошибка месячного отчёта: {e}")
        return None

def build_period_report_text(point_key, date_from, date_to, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1:
            return None
        stats = {}
        total_loss = 0
        for row in data[1:]:
            if len(row) >= 7:
                try:
                    row_date = datetime.strptime(row[0], "%d.%m.%Y").date()
                    if date_from <= row_date <= date_to:
                        product = row[3]
                        qty = float(row[4])
                        loss = float(row[6])
                        stats.setdefault(product, {"qty": 0, "loss": 0})
                        stats[product]["qty"] += qty
                        stats[product]["loss"] += loss
                        total_loss += loss
                except:
                    continue
        if not stats:
            return None
        point_name = POINTS[point_key]["name"]
        report = f"📊 ОТЧЁТ ЗА {date_from.strftime('%d.%m.%y')} – {date_to.strftime('%d.%m.%y')} ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices:
                report += f"{product}: {d['qty']:.0f} шт\n"
            else:
                report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        if not hide_prices:
            report += f"\n💰 ИТОГО: {total_loss:.0f} ₸"
        return report
    except Exception as e:
        logging.error(f"Ошибка отчёта за период: {e}")
        return None

def send_group_help(chat_id):
    help_text = (
        "Доступные команды:\n\n"
        "📊 /report — отчёт за 7 дней\n"
        "📅 /month — отчёт за текущий месяц\n"
        "📈 /period — отчёт за произвольный период\n"
        "❓ /help — эта справка"
    )
    send_message(chat_id, help_text)

# ========================
# WEBHOOK
# ========================

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()

        # ====================================
        # CALLBACK QUERY (нажатия inline-кнопок в группе)
        # ====================================
        if "callback_query" in update:
            cq = update["callback_query"]
            callback_id = cq["id"]
            data = cq.get("data", "")
            chat = cq["message"]["chat"]
            chat_id = chat["id"]
            chat_type = chat["type"]

            if chat_type == "private":
                answer_callback(callback_id)
                return jsonify({"status": "ok"}), 200

            group_key = str(chat_id)
            if group_key not in GROUP_TO_POINT:
                answer_callback(callback_id)
                return jsonify({"status": "ok"}), 200

            point_key = GROUP_TO_POINT[group_key]

            if data == "p7":
                answer_callback(callback_id)
                report = build_week_report_text(point_key, hide_prices=True)
                send_message(chat_id, report if report else "📭 За 7 дней списаний нет")
            elif data == "p30":
                answer_callback(callback_id)
                date_to = datetime.now(TIMEZONE).date()
                date_from = date_to - timedelta(days=30)
                report = build_period_report_text(point_key, date_from, date_to, hide_prices=True)
                send_message(chat_id, report if report else "📭 За 30 дней списаний нет")
            elif data == "pmonth":
                answer_callback(callback_id)
                report = build_month_report_text(point_key, hide_prices=True)
                send_message(chat_id, report if report else "📭 За этот месяц списаний нет")
            elif data == "pcustom":
                answer_callback(callback_id)
                user_data[chat_id] = {"waiting_for": "group_period_start"}
                send_message(chat_id, "📅 Введите дату НАЧАЛА в формате ДД.ММ.ГГ\n\nНапример: 01.09.26")
            elif data == "pcancel":
                answer_callback(callback_id, "Отменено")
            else:
                answer_callback(callback_id)

            return jsonify({"status": "ok"}), 200

        # ====================================
        # MESSAGE
        # ====================================
        if "message" not in update:
            return jsonify({"status": "ok"}), 200

        chat_id = update["message"]["chat"]["id"]
        chat_type = update["message"]["chat"]["type"]
        user_name = update["message"]["from"].get("first_name", "Гость")

        # ====================================
        # ЛИЧКА
        # ====================================
        if chat_type == "private":

            # ФОТО
            if "photo" in update["message"]:
                if chat_id in user_data and user_data[chat_id].get("waiting_for") == "point_photo":
                    try:
                        file_id = update["message"]["photo"][-1]["file_id"]
                        point_key = user_points.get(chat_id, "point_1")
                        point_name = POINTS[point_key]["name"]
                        now = datetime.now(TIMEZONE)
                        caption = f"📸 Обстановка на точке\n🏪 {point_name}\n👤 {user_name}\n🕐 {now.strftime('%d.%m.%Y %H:%M')}"
                        if send_photo_to_group(file_id, caption, point_key):
                            send_message(chat_id, "✅ Фото отправлено в группу!")
                        else:
                            send_message(chat_id, "❌ Ошибка отправки в группу")
                        del user_data[chat_id]
                        send_main_menu(chat_id, point_key)
                    except Exception as e:
                        logging.error(f"Ошибка фото: {e}")
                        send_message(chat_id, "❌ Ошибка обработки фото")
                else:
                    send_message(chat_id, "❌ Сначала нажмите 📸 Обстановка на точке")
                return jsonify({"status": "ok"}), 200

            text = update["message"].get("text", "").strip()

            if text == "/start":
                send_point_selection(chat_id)
                return jsonify({"status": "ok"}), 200

            for pk, pdata in POINTS.items():
                if text == f"🏠 {pdata['name']}":
                    user_points[chat_id] = pk
                    send_message(chat_id, f"✅ Точка: {pdata['name']}")
                    send_main_menu(chat_id, pk)
                    return jsonify({"status": "ok"}), 200

            if text == "🏪 Сменить точку":
                send_point_selection(chat_id)
                return jsonify({"status": "ok"}), 200

            if chat_id not in user_points:
                send_message(chat_id, "⚠️ Сначала выберите точку: /start")
                return jsonify({"status": "ok"}), 200
            point_key = user_points[chat_id]

            # КНОПКИ
            if text == "📊 Отчёты":
                send_reports_menu(chat_id, point_key)
                return jsonify({"status": "ok"}), 200
            if text == "📆 За текущую неделю":
                send_weekly_report(chat_id, point_key)
                return jsonify({"status": "ok"}), 200
            if text == "📅 За месяц":
                send_month_selection(chat_id)
                return jsonify({"status": "ok"}), 200
            if text == "📊 За период":
                user_data[chat_id] = {"waiting_for": "period_start"}
                send_message(chat_id,
                    "📅 Введите дату НАЧАЛА в формате ДД.ММ.ГГ\n\nНапример: 01.09.26",
                    reply_markup={"keyboard": [["◀️ Отмена"]], "resize_keyboard": True})
                return jsonify({"status": "ok"}), 200
            if text == "📸 Обстановка на точке":
                user_data[chat_id] = {"waiting_for": "point_photo"}
                send_message(chat_id, "📸 Отправьте фото:")
                return jsonify({"status": "ok"}), 200
            if text == "➕ Другое":
                user_data[chat_id] = {"waiting_for": "other_product"}
                send_message(chat_id, "✏️ Напишите название позиции:")
                return jsonify({"status": "ok"}), 200
            if text == "◀️ Назад":
                if chat_id in user_data:
                    del user_data[chat_id]
                send_main_menu(chat_id, point_key)
                return jsonify({"status": "ok"}), 200
            if text == "◀️ Отмена":
                if chat_id in user_data:
                    del user_data[chat_id]
                send_reports_menu(chat_id, point_key)
                return jsonify({"status": "ok"}), 200

            # ВВОД ДАТЫ НАЧАЛА ПЕРИОДА
            if chat_id in user_data and user_data[chat_id].get("waiting_for") == "period_start":
                d = parse_short_date(text)
                if not d:
                    send_message(chat_id, "❌ Неверный формат. Введите как ДД.ММ.ГГ\nНапример: 01.09.26",
                                 reply_markup={"keyboard": [["◀️ Отмена"]], "resize_keyboard": True})
                    return jsonify({"status": "ok"}), 200
                user_data[chat_id] = {"waiting_for": "period_end", "date_from": d}
                send_message(chat_id, "📅 Введите дату КОНЦА в формате ДД.ММ.ГГ\n\nНапример: 15.09.26",
                             reply_markup={"keyboard": [["◀️ Отмена"]], "resize_keyboard": True})
                return jsonify({"status": "ok"}), 200

            if chat_id in user_data and user_data[chat_id].get("waiting_for") == "period_end":
                d_end = parse_short_date(text)
                if not d_end:
                    send_message(chat_id, "❌ Неверный формат. Введите как ДД.ММ.ГГ\nНапример: 15.09.26",
                                 reply_markup={"keyboard": [["◀️ Отмена"]], "resize_keyboard": True})
                    return jsonify({"status": "ok"}), 200
                d_start = user_data[chat_id]["date_from"]
                if d_end < d_start:
                    send_message(chat_id, "❌ Дата конца раньше начала. Введите КОНЕЦ ещё раз:")
                    return jsonify({"status": "ok"}), 200
                send_period_report(chat_id, point_key, d_start, d_end)
                del user_data[chat_id]
                send_reports_menu(chat_id, point_key)
                return jsonify({"status": "ok"}), 200

            # ВЫБОР МЕСЯЦА
            if text in MONTHS:
                current_year = datetime.now(TIMEZONE).year
                user_data[chat_id] = {"waiting_for": "week_in_month", "month": text, "year": current_year}
                send_week_selection(chat_id, text, current_year)
                return jsonify({"status": "ok"}), 200

            if chat_id in user_data and user_data[chat_id].get("waiting_for") == "week_in_month":
                month = user_data[chat_id]["month"]
                year = user_data[chat_id]["year"]
                if text == "Весь месяц":
                    send_monthly_report(chat_id, month, year, point_key)
                elif " " in text and text.split(" ")[0].split("-")[0].isdigit():
                    week_part = text.split(" ")[0]
                    if "-" in week_part:
                        start, end = map(int, week_part.split("-"))
                        send_monthly_report(chat_id, month, year, point_key, (start, end))
                    else:
                        d = int(week_part)
                        send_monthly_report(chat_id, month, year, point_key, (d, d))
                del user_data[chat_id]
                send_reports_menu(chat_id, point_key)
                return jsonify({"status": "ok"}), 200

            # ВВОД КОЛИЧЕСТВА
            if chat_id in user_data and user_data[chat_id].get("waiting_for") in ["quantity", "quantity_other"]:
                try:
                    quantity = float(text.replace(",", "."))
                    product = user_data[chat_id]["product"]
                    success, loss = save_to_sheet(user_name, product, quantity, point_key)
                    if success:
                        send_message(chat_id, f"✅ Списано: {product} — {quantity} шт")
                    else:
                        send_message(chat_id, "❌ Ошибка сохранения")
                    del user_data[chat_id]
                    send_main_menu(chat_id, point_key)
                except ValueError:
                    send_message(chat_id, "❌ Введите число:")
                return jsonify({"status": "ok"}), 200

            if chat_id in user_data and user_data[chat_id].get("waiting_for") == "other_product":
                product = text
                user_data[chat_id] = {"waiting_for": "quantity_other", "product": product}
                send_message(chat_id, f"📝 Введите количество для {product}:")
                return jsonify({"status": "ok"}), 200

            menu = get_menu(point_key)
            if text in menu:
                send_category_menu(chat_id, text, point_key)
                return jsonify({"status": "ok"}), 200

            for cat, items in menu.items():
                for name, price in items:
                    if text == name:
                        user_data[chat_id] = {"waiting_for": "quantity", "product": name}
                        send_message(chat_id, f"📝 Введите количество для {name}:")
                        return jsonify({"status": "ok"}), 200

            send_message(chat_id, "❌ Используйте кнопки меню")
            return jsonify({"status": "ok"}), 200

        # ====================================
        # ГРУППА (только команды, БЕЗ ЦЕН)
        # ====================================
        group_key = str(chat_id)
        if group_key not in GROUP_TO_POINT:
            return jsonify({"status": "ok"}), 200

        point_key = GROUP_TO_POINT[group_key]
        text = update["message"].get("text", "").strip()

        # Ожидание ввода дат
        if chat_id in user_data:
            state = user_data[chat_id]

            if state.get("waiting_for") == "group_period_start":
                d = parse_short_date(text)
                if not d:
                    send_message(chat_id, "❌ Неверный формат. Введите как ДД.ММ.ГГ\nНапример: 01.09.26")
                    return jsonify({"status": "ok"}), 200
                user_data[chat_id] = {"waiting_for": "group_period_end", "date_from": d}
                send_message(chat_id, "📅 Введите дату КОНЦА в формате ДД.ММ.ГГ\nНапример: 15.09.26")
                return jsonify({"status": "ok"}), 200

            if state.get("waiting_for") == "group_period_end":
                d_end = parse_short_date(text)
                if not d_end:
                    send_message(chat_id, "❌ Неверный формат. Введите как ДД.ММ.ГГ\nНапример: 15.09.26")
                    return jsonify({"status": "ok"}), 200
                d_start = state["date_from"]
                if d_end < d_start:
                    send_message(chat_id, "❌ Дата конца раньше начала. Введите КОНЕЦ ещё раз:")
                    return jsonify({"status": "ok"}), 200
                report = build_period_report_text(point_key, d_start, d_end, hide_prices=True)
                send_message(chat_id, report if report else "📭 За этот период списаний нет")
                del user_data[chat_id]
                return jsonify({"status": "ok"}), 200

            return jsonify({"status": "ok"}), 200

        # Не команда — молчим
        if not text.startswith("/"):
            return jsonify({"status": "ok"}), 200

        cmd = text.split()[0].split("@")[0]

        if cmd == "/help":
            send_group_help(chat_id)
        elif cmd == "/report":
            report = build_week_report_text(point_key, hide_prices=True)
            send_message(chat_id, report if report else "📭 За 7 дней списаний нет")
        elif cmd == "/month":
            report = build_month_report_text(point_key, hide_prices=True)
            send_message(chat_id, report if report else "📭 За этот месяц списаний нет")
        elif cmd == "/period":
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📆 За 7 дней", "callback_data": "p7"},
                        {"text": "📅 За 30 дней", "callback_data": "p30"}
                    ],
                    [
                        {"text": "📅 Этот месяц", "callback_data": "pmonth"},
                        {"text": "📊 Свой период", "callback_data": "pcustom"}
                    ],
                    [
                        {"text": "◀️ Отмена", "callback_data": "pcancel"}
                    ]
                ]
            }
            send_message(chat_id, "Выберите период:", reply_markup=keyboard)
        else:
            send_message(chat_id, "❌ Неизвестная команда. Список: /help")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот учёта списаний (2 точки) работает!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)