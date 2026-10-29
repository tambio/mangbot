import os
import logging
import urllib.parse
from flask import Flask, request, jsonify, send_file
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

CRON_SECRET = os.environ.get("CRON_SECRET", "")

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
        items = []
        for row in data[1:]:
            if len(row) >= 2 and row[0].strip():
                name = row[0].strip()
                try:
                    price = float(row[1])
                except:
                    price = 0
                items.append((name, price))
        return items
    except Exception as e:
        logging.error(f"Ошибка чтения меню: {e}")
        return []

def get_price(product_name, point_key):
    items = get_menu(point_key)
    for name, price in items:
        if name == product_name:
            return price
    return 0

def get_employees(point_key):
    try:
        sheet = get_sheet("Сотрудники", point_key)
        data = sheet.get_all_values()
        usernames = []
        for row in data[1:]:
            if len(row) >= 1 and row[0].strip():
                username = row[0].strip().lstrip("@")
                if username:
                    usernames.append(username)
        return usernames
    except Exception as e:
        logging.error(f"Ошибка чтения сотрудников: {e}")
        return []

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
# WEB APP API
# ========================

@app.route('/webapp')
def webapp():
    return send_file('webapp.html')

@app.route('/api/menu')
def api_menu():
    point_key = request.args.get('point', 'point_1')
    items = get_menu(point_key)
    return jsonify([{"name": name, "price": price} for name, price in items])

@app.route('/api/submit', methods=['POST'])
def api_submit():
    try:
        data = request.get_json()
        chat_id = data.get('chat_id')
        user_name = data.get('user_name')
        point_key = data.get('point_key')
        cart = data.get('cart', {})

        if not cart:
            return jsonify({"status": "error", "message": "Корзина пуста"})

        sheet = get_sheet("СПИСАНИЕ", point_key)
        now = datetime.now(TIMEZONE)
        date_str = now.strftime("%d.%m.%Y")
        time_str = now.strftime("%H:%M:%S")

        rows_to_insert = []
        for product_name, qty in cart.items():
            price = get_price(product_name, point_key)
            loss = price * qty
            rows_to_insert.append([date_str, time_str, user_name, product_name, str(qty), str(price), str(loss)])

        sheet.append_rows(rows_to_insert)
        
        # Уведомление в группу
        group_id = POINTS[point_key].get("group_id")
        if group_id:
            text = f"📦 {user_name} списал(а):\n"
            for p, q in cart.items():
                text += f"• {p} — {q} шт\n"
            send_message(group_id, text)

        return jsonify({"status": "ok"})
    except Exception as e:
        logging.error(f"Ошибка витрины: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/report', methods=['POST'])
def api_report():
    try:
        data = request.get_json()
        point_key = data.get('point_key')
        report_type = data.get('type')
        date_from = data.get('date_from')
        date_to = data.get('date_to')

        sheet = get_sheet("СПИСАНИЕ", point_key)
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return jsonify({"status": "ok", "data": [], "total_loss": 0, "show_prices": report_type == 'sverka'})

        stats = {}
        total_loss = 0
        now = datetime.now(TIMEZONE)

        for row in rows[1:]:
            if len(row) < 7: continue
            try:
                row_date = datetime.strptime(row[0], "%d.%m.%Y").date()
                
                if report_type == 'week':
                    week_ago = now.date() - timedelta(days=7)
                    if row_date < week_ago: continue
                elif report_type == 'month':
                    if row_date.year != now.year or row_date.month != now.month: continue
                elif report_type in ['period', 'sverka']:
                    d_from = datetime.strptime(date_from, "%d.%m.%y").date()
                    d_to = datetime.strptime(date_to, "%d.%m.%y").date()
                    if not (d_from <= row_date <= d_to): continue

                product = row[3]
                qty = float(row[4])
                loss = float(row[6])
                
                stats.setdefault(product, {"qty": 0, "loss": 0})
                stats[product]["qty"] += qty
                stats[product]["loss"] += loss
                total_loss += loss
            except:
                continue

        result = []
        for prod, d in stats.items():
            result.append({"product": prod, "qty": d["qty"], "loss": d["loss"]})
        
        result.sort(key=lambda x: x["qty"], reverse=True)
        show_prices = (report_type == 'sverka')
        
        return jsonify({
            "status": "ok", 
            "data": result, 
            "total_loss": total_loss,
            "show_prices": show_prices
        })
    except Exception as e:
        logging.error(f"Ошибка API отчета: {e}")
        return jsonify({"status": "error", "message": str(e)})


# ========================
# МЕНЮ БОТА (ТОЛЬКО MINI APP)
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

def send_main_menu(chat_id, point_key, user_name="Гость"):
    point_name = POINTS[point_key]["name"]
    safe_point_name = urllib.parse.quote(point_name)
    
    # Ссылка на наш Mini App с параметрами
    web_app_url = f"https://coffee-spisanie-bot.onrender.com/webapp?point={point_key}&user={user_name}&chat_id={chat_id}&point_name={safe_point_name}"
    
    # Инлайн-кнопка для запуска Mini App
    inline_keyboard = {
        "inline_keyboard": [[
            {"text": f"🚀 Открыть Kontrol ({point_name})", "web_app": {"url": web_app_url}}
        ]]
    }
    
    # Клавиатура снизу (только для сброса)
    reply_keyboard = {
        "keyboard": [["🏠 Главное меню"]],
        "resize_keyboard": True
    }
    
    send_message(chat_id, f"📍 Точка: {point_name}\n\nНажмите кнопку ниже, чтобы открыть приложение Kontrol 👇", reply_markup=inline_keyboard)
    send_message(chat_id, "Или используйте меню для возврата:", reply_markup=reply_keyboard)

# ========================
# ОТЧЁТЫ ДЛЯ ГРУПП И CRON
# ========================

def build_week_report_text(point_key, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1: return None
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
                except: continue
        if not stats: return None
        point_name = POINTS[point_key]["name"]
        report = f"📊 ОТЧЁТ ЗА НЕДЕЛЮ ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices: report += f"{product}: {d['qty']:.0f} шт\n"
            else: report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        return report
    except Exception as e:
        logging.error(f"Ошибка недельного отчёта: {e}")
        return None

def build_month_report_text(point_key, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1: return None
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
                except: continue
        if not stats: return None
        point_name = POINTS[point_key]["name"]
        month_name = MONTHS[now.month - 1]
        report = f"📊 ОТЧЁТ ЗА {month_name} {now.year} ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices: report += f"{product}: {d['qty']:.0f} шт\n"
            else: report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        return report
    except Exception as e:
        logging.error(f"Ошибка месячного отчёта: {e}")
        return None

def build_period_report_text(point_key, date_from, date_to, hide_prices=False):
    try:
        sheet = get_sheet("СПИСАНИЕ", point_key)
        data = sheet.get_all_values()
        if len(data) <= 1: return None
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
                except: continue
        if not stats: return None
        point_name = POINTS[point_key]["name"]
        report = f"📊 ОТЧЁТ ЗА {date_from.strftime('%d.%m.%y')} – {date_to.strftime('%d.%m.%y')} ({point_name})\n\n"
        for product, d in stats.items():
            if hide_prices: report += f"{product}: {d['qty']:.0f} шт\n"
            else: report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        if not hide_prices: report += f"\n💰 ИТОГО: {total_loss:.0f} ₸"
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
# CRON (автоотчёты + напоминания)
# ========================

@app.route('/cron/weekly', methods=['GET'])
def cron_weekly():
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    for point_key, pdata in POINTS.items():
        group_id = pdata.get("group_id")
        if not group_id: continue
        report = build_week_report_text(point_key, hide_prices=True)
        if report: send_message(group_id, report)
        else: send_message(group_id, f"📭 За неделю списаний нет ({pdata['name']})")
    return jsonify({"status": "ok"}), 200

@app.route('/cron/monthly', methods=['GET'])
def cron_monthly():
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    for point_key, pdata in POINTS.items():
        group_id = pdata.get("group_id")
        if not group_id: continue
        report = build_month_report_text(point_key, hide_prices=True)
        if report: send_message(group_id, report)
        else: send_message(group_id, f"📭 За этот месяц списаний нет ({pdata['name']})")
    return jsonify({"status": "ok"}), 200

@app.route('/cron/remind', methods=['GET'])
def cron_remind():
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "unauthorized"}), 403
    results = []
    for point_key, pdata in POINTS.items():
        group_id = pdata.get("group_id")
        if not group_id: continue
        usernames = get_employees(point_key)
        if not usernames:
            results.append({"point": pdata["name"], "status": "no_employees"})
            continue
        tags = " ".join([f"@{u}" for u in usernames])
        text = f"🔔 {tags}\n\nНапоминание: не забудь! внести списания за сегодня!\n📍 Точка: {pdata['name']}"
        send_message(group_id, text)
        results.append({"point": pdata["name"], "status": "sent", "count": len(usernames)})
    return jsonify({"status": "ok", "results": results}), 200

# ========================
# WEBHOOK
# ========================

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()

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

        if "message" not in update:
            return jsonify({"status": "ok"}), 200

        chat_id = update["message"]["chat"]["id"]
        chat_type = update["message"]["chat"]["type"]
        user_name = update["message"]["from"].get("first_name", "Гость")

        # ЛИЧКА (ТОЛЬКО MINI APP)
        if chat_type == "private":
            # Обработка фото, если бариста отправит его боту (на будущее)
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
                        send_main_menu(chat_id, point_key, user_name)
                    except Exception as e:
                        logging.error(f"Ошибка фото: {e}")
                        send_message(chat_id, "❌ Ошибка обработки фото")
                return jsonify({"status": "ok"}), 200

            text = update["message"].get("text", "").strip()

            if text == "/start" or text == "🏠 Главное меню":
                user_points.pop(chat_id, None)
                if chat_id in user_data: del user_data[chat_id]
                send_point_selection(chat_id)
                return jsonify({"status": "ok"}), 200

            for pk, pdata in POINTS.items():
                if text == f"🏠 {pdata['name']}":
                    user_points[chat_id] = pk
                    send_message(chat_id, f"✅ Точка: {pdata['name']}")
                    send_main_menu(chat_id, pk, user_name)
                    return jsonify({"status": "ok"}), 200

            if chat_id not in user_points:
                send_point_selection(chat_id)
                return jsonify({"status": "ok"}), 200
            
            # Любое другое сообщение перекидывает на главное меню с Mini App
            point_key = user_points[chat_id]
            send_main_menu(chat_id, point_key, user_name)
            return jsonify({"status": "ok"}), 200

        # ГРУППА (оставляем только команды, без цен)
        group_key = str(chat_id)
        if group_key not in GROUP_TO_POINT:
            return jsonify({"status": "ok"}), 200

        point_key = GROUP_TO_POINT[group_key]
        text = update["message"].get("text", "").strip()

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
    return "Kontrol — бот учёта списаний работает!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)