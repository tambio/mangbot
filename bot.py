import os
import logging
from flask import Flask, request, jsonify
import requests
from datetime import datetime, timedelta
import calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SHEET_ID = os.environ.get("SHEET_ID")
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

user_data = {}

MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

# ========================
# GOOGLE SHEETS
# ========================

def get_sheet(sheet_name):
    creds_path = '/etc/secrets/credentials.json'
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(sheet_name)

def get_menu():
    """Читает лист 'Прайс'. Возвращает {категория: [(название, цена)]}"""
    try:
        sheet = get_sheet("Прайс")
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

def get_price(product_name):
    """Ищет цену по названию товара"""
    menu = get_menu()
    for cat, items in menu.items():
        for name, price in items:
            if name == product_name:
                return price
    return 0

def add_product(category, name, price):
    """Добавляет строку в лист 'Прайс'"""
    try:
        sheet = get_sheet("Прайс")
        sheet.append_row([category, name, str(price)])
        return True
    except Exception as e:
        logging.error(f"Ошибка добавления: {e}")
        return False

def find_row_by_name(name):
    """Возвращает номер строки (1-based) по названию или None"""
    try:
        sheet = get_sheet("Прайс")
        data = sheet.get_all_values()
        for i, row in enumerate(data):
            if len(row) >= 2 and row[1].strip() == name:
                return i + 1
        return None
    except Exception as e:
        logging.error(f"Ошибка поиска: {e}")
        return None

def delete_product(name):
    row = find_row_by_name(name)
    if not row:
        return False
    try:
        sheet = get_sheet("Прайс")
        sheet.delete_rows(row)
        return True
    except Exception as e:
        logging.error(f"Ошибка удаления: {e}")
        return False

def update_price(name, new_price):
    row = find_row_by_name(name)
    if not row:
        return False
    try:
        sheet = get_sheet("Прайс")
        sheet.update_cell(row, 3, str(new_price))
        return True
    except Exception as e:
        logging.error(f"Ошибка обновления цены: {e}")
        return False

def save_to_sheet(user_name, product, quantity):
    try:
        sheet = get_sheet("СПИСАНИЕ")
        price = get_price(product)
        loss = price * quantity
        now = datetime.now()
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
# ОТПРАВКА СООБЩЕНИЙ
# ========================

def send_message(chat_id, text, reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")

def send_photo_to_group(file_id, caption):
    try:
        url = f"{TELEGRAM_API_URL}/sendPhoto"
        payload = {"chat_id": GROUP_CHAT_ID, "photo": file_id, "caption": caption}
        r = requests.post(url, json=payload)
        logging.info(f"Фото в группу: {r.status_code} — {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        logging.error(f"Ошибка отправки фото в группу: {e}")
        return False

# ========================
# МЕНЮ
# ========================

def send_main_menu(chat_id):
    menu = get_menu()
    categories = list(menu.keys())
    keyboard = []
    row = []
    for i, cat in enumerate(categories):
        row.append(cat)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(["📊 Отчёты", "📸 Обстановка на точке"])
    keyboard.append(["➕ Другое"])
    keyboard_obj = {"keyboard": keyboard, "resize_keyboard": True}
    send_message(chat_id, "🍽 ВЫБЕРИТЕ КАТЕГОРИЮ:", reply_markup=keyboard_obj)

def send_category_menu(chat_id, category):
    menu = get_menu()
    items = menu.get(category, [])
    if not items:
        send_message(chat_id, f"❌ В категории «{category}» нет товаров")
        send_main_menu(chat_id)
        return
    keyboard = []
    for name, price in items:
        keyboard.append([name])
    keyboard.append(["◀️ Назад"])
    keyboard_obj = {"keyboard": keyboard, "resize_keyboard": True}
    send_message(chat_id, f"📦 {category} — выберите товар:", reply_markup=keyboard_obj)

def send_reports_menu(chat_id):
    keyboard = {"keyboard": [
        ["📆 За текущую неделю"],
        ["📅 За месяц"],
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
    keyboard = {"keyboard": months_kb, "resize_keyboard": True}
    send_message(chat_id, "🗓 ВЫБЕРИТЕ МЕСЯЦ:", reply_markup=keyboard)

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
    keyboard_obj = {"keyboard": keyboard, "resize_keyboard": True}
    send_message(chat_id, f"🗓 {month_name.upper()} {year} — выберите неделю:", reply_markup=keyboard_obj)

# ========================
# ОТЧЁТЫ
# ========================

def send_weekly_report(chat_id):
    try:
        sheet = get_sheet("СПИСАНИЕ")
        data = sheet.get_all_values()
        if len(data) <= 1:
            send_message(chat_id, "📭 За неделю списаний нет")
            return
        week_ago = datetime.now() - timedelta(days=7)
        stats = {}
        total_loss = 0
        for row in data[1:]:
            if len(row) >= 7:
                try:
                    row_date = datetime.strptime(row[0], "%d.%m.%Y")
                    if row_date >= week_ago:
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
            send_message(chat_id, "📭 За последнюю неделю списаний нет")
            return
        report = "📊 ОТЧЁТ ЗА НЕДЕЛЮ\n\n"
        for product, d in stats.items():
            report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        report += f"\n💰 ИТОГО УБЫТОК: {total_loss:.0f} ₸"
        send_message(chat_id, report)
    except Exception as e:
        logging.error(f"Ошибка отчёта: {e}")
        send_message(chat_id, "❌ Ошибка формирования отчёта")

def send_monthly_report(chat_id, month_name, year, week_range=None):
    try:
        sheet = get_sheet("СПИСАНИЕ")
        data = sheet.get_all_values()
        if len(data) <= 1:
            send_message(chat_id, "📭 За указанный период списаний нет")
            return
        month_num = MONTHS.index(month_name) + 1
        stats = {}
        total_loss = 0
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
                        total_loss += loss
                except:
                    continue
        if not stats:
            send_message(chat_id, "📭 За указанный период списаний нет")
            return
        if week_range:
            report = f"📊 ОТЧЁТ ЗА {week_range[0]}-{week_range[1]} {month_name} {year}\n\n"
        else:
            report = f"📊 ОТЧЁТ ЗА {month_name} {year}\n\n"
        for product, d in stats.items():
            report += f"{product}: {d['qty']} шт — {d['loss']:.0f} ₸\n"
        report += f"\n💰 ИТОГО УБЫТОК: {total_loss:.0f} ₸"
        send_message(chat_id, report)
    except Exception as e:
        logging.error(f"Ошибка отчёта: {e}")
        send_message(chat_id, "❌ Ошибка формирования отчёта")

# ========================
# WEBHOOK
# ========================

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if "message" not in update:
            return jsonify({"status": "ok"}), 200

        # Игнорируем группы и каналы
        if update["message"]["chat"]["type"] != "private":
            return jsonify({"status": "ok"}), 200

        chat_id = update["message"]["chat"]["id"]
        user_id = update["message"]["from"].get("id")
        user_name = update["message"]["from"].get("first_name", "Гость")
        is_admin = user_id in ADMIN_IDS

        # ===== ФОТО =====
        if "photo" in update["message"]:
            if chat_id in user_data and user_data[chat_id].get("waiting_for") == "point_photo":
                try:
                    file_id = update["message"]["photo"][-1]["file_id"]
                    now = datetime.now()
                    caption = f"📸 Обстановка на точке\n👤 {user_name}\n🕐 {now.strftime('%d.%m.%Y %H:%M')}"
                    if send_photo_to_group(file_id, caption):
                        send_message(chat_id, "✅ Фото отправлено в группу!")
                    else:
                        send_message(chat_id, "❌ Ошибка отправки в группу")
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                except Exception as e:
                    logging.error(f"Ошибка фото: {e}")
                    send_message(chat_id, "❌ Ошибка обработки фото")
            else:
                send_message(chat_id, "❌ Сначала нажмите 📸 Обстановка на точке")
            return jsonify({"status": "ok"}), 200

        # ===== ТЕКСТ =====
        text = update["message"].get("text", "").strip()

        # ===== АДМИН-КОМАНДЫ =====
        if is_admin and text.startswith("/add"):
            parts = text[4:].split("|")
            if len(parts) == 3:
                cat, name, price = [p.strip() for p in parts]
                try:
                    price_val = float(price)
                    if add_product(cat, name, price_val):
                        send_message(chat_id, f"✅ Добавлено:\n📁 {cat}\n📦 {name}\n💰 {price_val} ₸")
                    else:
                        send_message(chat_id, "❌ Ошибка добавления")
                except ValueError:
                    send_message(chat_id, "❌ Цена должна быть числом")
            else:
                send_message(chat_id, "📝 Формат: /add Категория | Название | Цена\nПример: /add Круассан | 🥐 Круассан фисташка | 120")
            return jsonify({"status": "ok"}), 200

        if is_admin and text.startswith("/del"):
            name = text[4:].strip()
            if not name:
                send_message(chat_id, "📝 Формат: /del Название\nПример: /del 🥐 Круассан фисташка")
                return jsonify({"status": "ok"}), 200
            if delete_product(name):
                send_message(chat_id, f"✅ Удалено: {name}")
            else:
                send_message(chat_id, f"❌ Товар «{name}» не найден")
            return jsonify({"status": "ok"}), 200

        if is_admin and text.startswith("/edit"):
            parts = text[5:].split("|")
            if len(parts) == 2:
                name, price = [p.strip() for p in parts]
                try:
                    price_val = float(price)
                    if update_price(name, price_val):
                        send_message(chat_id, f"✅ Цена обновлена:\n📦 {name} → {price_val} ₸")
                    else:
                        send_message(chat_id, f"❌ Товар «{name}» не найден")
                except ValueError:
                    send_message(chat_id, "❌ Цена должна быть числом")
            else:
                send_message(chat_id, "📝 Формат: /edit Название | Новая цена\nПример: /edit 🥐 Круассан фисташка | 150")
            return jsonify({"status": "ok"}), 200

        if is_admin and text == "/list":
            menu = get_menu()
            if not menu:
                send_message(chat_id, "📭 Товаров нет")
            else:
                msg = "📋 <b>ВСЕ ТОВАРЫ</b>\n\n"
                for cat, items in menu.items():
                    msg += f"<b>📁 {cat}</b>\n"
                    for name, price in items:
                        msg += f"  • {name} — {price} ₸\n"
                    msg += "\n"
                send_message(chat_id, msg)
            return jsonify({"status": "ok"}), 200

        if text == "/start":
            send_main_menu(chat_id)
            return jsonify({"status": "ok"}), 200

        # ===== СЕРВИСНЫЕ КНОПКИ =====
        if text == "📊 Отчёты":
            send_reports_menu(chat_id)
            return jsonify({"status": "ok"}), 200
        if text == "📆 За текущую неделю":
            send_weekly_report(chat_id)
            return jsonify({"status": "ok"}), 200
        if text == "📅 За месяц":
            send_month_selection(chat_id)
            return jsonify({"status": "ok"}), 200
        if text == "📸 Обстановка на точке":
            user_data[chat_id] = {"waiting_for": "point_photo"}
            send_message(chat_id, "📸 Отправьте фото обстановки на точке:")
            return jsonify({"status": "ok"}), 200
        if text == "➕ Другое":
            user_data[chat_id] = {"waiting_for": "other_product"}
            send_message(chat_id, "✏️ Напишите название позиции:")
            return jsonify({"status": "ok"}), 200
        if text == "◀️ Назад":
            if chat_id in user_data:
                del user_data[chat_id]
            send_main_menu(chat_id)
            return jsonify({"status": "ok"}), 200

        # ===== ВЫБОР МЕСЯЦА =====
        if text in MONTHS:
            current_year = datetime.now().year
            user_data[chat_id] = {"waiting_for": "week_in_month", "month": text, "year": current_year}
            send_week_selection(chat_id, text, current_year)
            return jsonify({"status": "ok"}), 200

        if chat_id in user_data and user_data[chat_id].get("waiting_for") == "week_in_month":
            month = user_data[chat_id]["month"]
            year = user_data[chat_id]["year"]
            if text == "Весь месяц":
                send_monthly_report(chat_id, month, year)
            elif " " in text and text.split(" ")[0].split("-")[0].isdigit():
                week_part = text.split(" ")[0]
                if "-" in week_part:
                    start, end = map(int, week_part.split("-"))
                    send_monthly_report(chat_id, month, year, (start, end))
                else:
                    d = int(week_part)
                    send_monthly_report(chat_id, month, year, (d, d))
            del user_data[chat_id]
            send_reports_menu(chat_id)
            return jsonify({"status": "ok"}), 200

        # ===== ВВОД КОЛИЧЕСТВА =====
        if chat_id in user_data and user_data[chat_id].get("waiting_for") in ["quantity", "quantity_other"]:
            try:
                quantity = float(text.replace(",", "."))
                product = user_data[chat_id]["product"]
                success, loss = save_to_sheet(user_name, product, quantity)
                if success:
                    send_message(chat_id, f"✅ Списано: {product} — {quantity} шт\n💰 Убыток: {loss:.0f} ₸")
                else:
                    send_message(chat_id, "❌ Ошибка сохранения")
                del user_data[chat_id]
                send_main_menu(chat_id)
            except ValueError:
                send_message(chat_id, "❌ Введите число:")
            return jsonify({"status": "ok"}), 200

        # ===== РУЧНОЙ ВВОД ТОВАРА (Другое) =====
        if chat_id in user_data and user_data[chat_id].get("waiting_for") == "other_product":
            product = text
            user_data[chat_id] = {"waiting_for": "quantity_other", "product": product}
            send_message(chat_id, f"📝 Введите количество для {product}:")
            return jsonify({"status": "ok"}), 200

        # ===== ДИНАМИЧЕСКИЕ КАТЕГОРИИ =====
        menu = get_menu()
        if text in menu:
            send_category_menu(chat_id, text)
            return jsonify({"status": "ok"}), 200

        # ===== ДИНАМИЧЕСКИЕ ТОВАРЫ =====
        for cat, items in menu.items():
            for name, price in items:
                if text == name:
                    user_data[chat_id] = {"waiting_for": "quantity", "product": name}
                    send_message(chat_id, f"📝 Введите количество для {name}:")
                    return jsonify({"status": "ok"}), 200

        send_message(chat_id, "❌ Используйте кнопки меню")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот учёта списаний работает!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)