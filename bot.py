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
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Хранилище временных данных пользователей
user_data = {}

# от сюда надо к отчетам закинуть
MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

def get_sheet(sheet_name):
    """Подключение к указанному листу Google Sheets"""
    creds_path = '/etc/secrets/credentials.json'
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(sheet_name)

def get_price(product_name):
    """Получает себестоимость продукта из листа 'Прайс'"""
    try:
        prices_sheet = get_sheet("Прайс")
        all_prices = prices_sheet.get_all_values()
        for row in all_prices[1:]:
            if len(row) >= 2 and row[0] == product_name:
                try:
                    return float(row[1])
                except:
                    return 0
        return 0
    except Exception as e:
        logging.error(f"Ошибка получения цены: {e}")
        return 0

def save_to_sheet(user_name, product, quantity):
    """Сохраняет списание с расчётом убытка"""
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
        logging.info(f"Сохранено: {user_name} - {product} - {quantity} шт, убыток: {loss} ₸")
        return True, loss
    except Exception as e:
        logging.error(f"Ошибка Google Sheets: {e}")
        return False, 0

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
            ["🍱 Ролл", "📊 Отчёты"],
            ["➕ Другое"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🍽 ВЫБЕРИТЕ КАТЕГОРИЮ:", reply_markup=keyboard)

def send_reports_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["📆 За текущую неделю"],
            ["📅 За месяц"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "📊 ВЫБЕРИТЕ ТИП ОТЧЁТА:", reply_markup=keyboard)

def send_month_selection(chat_id):
    months_kb = []
    row = []
    for i, month in enumerate(MONTHS):
        row.append(month)
        if len(row) == 3 or i == len(MONTHS)-1:
            months_kb.append(row.copy())
            row = []
    months_kb.append(["◀️ Назад"])
    keyboard = {"keyboard": months_kb, "resize_keyboard": True}
    send_message(chat_id, "🗓 ВЫБЕРИТЕ МЕСЯЦ:", reply_markup=keyboard)

def send_week_selection(chat_id, month_name, year):
    """Формирует список недель для выбранного месяца"""
    month_num = MONTHS.index(month_name) + 1
    last_day = calendar.monthrange(year, month_num)[1]
    
    weeks = []
    week_start = 1
    while week_start <= last_day:
        week_end = min(week_start + 6, last_day)
        weeks.append((week_start, week_end))
        week_start += 7
    
    keyboard = []
    for ws, we in weeks:
        if ws == we:
            keyboard.append([f"{ws} {month_name}"])
        else:
            keyboard.append([f"{ws}-{we} {month_name}"])
    
    if last_day > 28:
        last_week_end = weeks[-1][1]
        if last_week_end < last_day:
            keyboard.append([f"{last_week_end+1}-{last_day} {month_name}"])
    
    keyboard.append(["Весь месяц", "◀️ Назад"])
    keyboard_obj = {"keyboard": keyboard, "resize_keyboard": True}
    send_message(chat_id, f"🗓 {month_name.upper()} {year} — ВЫБЕРИТЕ НЕДЕЛЮ:", reply_markup=keyboard_obj)

def send_weekly_report(chat_id):
    """Отчёт за последние 7 дней"""
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
                        quantity = float(row[4])
                        loss = float(row[6])
                        if product not in stats:
                            stats[product] = {"quantity": 0, "loss": 0}
                        stats[product]["quantity"] += quantity
                        stats[product]["loss"] += loss
                        total_loss += loss
                except:
                    continue
        
        if not stats:
            send_message(chat_id, "📭 За последнюю неделю списаний нет")
            return
        
        report = "📊 ОТЧЁТ ЗА НЕДЕЛЮ\n\n"
        for product, data in stats.items():
            report += f"{product}: {data['quantity']} шт — {data['loss']:.0f} ₸\n"
        report += f"\n💰 ИТОГО СУММА СПИСАНИЙ: {total_loss:.0f} ₸"
        send_message(chat_id, report)
    except Exception as e:
        logging.error(f"Ошибка отчёта: {e}")
        send_message(chat_id, "❌ Ошибка формирования отчёта")

def send_monthly_report(chat_id, month_name, year, week_range=None):
    """Отчёт за месяц или конкретную неделю месяца"""
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
                        if week_range:
                            day = row_date.day
                            if not (week_range[0] <= day <= week_range[1]):
                                continue
                        product = row[3]
                        quantity = float(row[4])
                        loss = float(row[6])
                        if product not in stats:
                            stats[product] = {"quantity": 0, "loss": 0}
                        stats[product]["quantity"] += quantity
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
        
        for product, data in stats.items():
            report += f"{product}: {data['quantity']} шт — {data['loss']:.0f} ₸\n"
        report += f"\n💰 ИТОГО СУММА СПИСАНИЙ: {total_loss:.0f} ₸"
        send_message(chat_id, report)
    except Exception as e:
        logging.error(f"Ошибка отчёта: {e}")
        send_message(chat_id, "❌ Ошибка формирования отчёта")

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

def send_sloika_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🥐 Слойка индейка"],
            ["◀️ Назад"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "🥐 ВЫБЕРИТЕ СЛОЙКУ:", reply_markup=keyboard)

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
            
            # ---- ОТЧЁТЫ ----
            elif text == "📊 Отчёты":
                send_reports_menu(chat_id)
            elif text == "📆 За текущую неделю":
                send_weekly_report(chat_id)
            elif text == "📅 За месяц":
                send_month_selection(chat_id)
            
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
            
            # ---- ВЫБОР МЕСЯЦА ----
            elif text in MONTHS:
                current_year = datetime.now().year
                user_data[chat_id] = {"waiting_for": "week_in_month", "month": text, "year": current_year}
                send_week_selection(chat_id, text, current_year)
            
            # ---- ВЫБОР НЕДЕЛИ В МЕСЯЦЕ ----
            elif chat_id in user_data and user_data[chat_id].get("waiting_for") == "week_in_month":
                month = user_data[chat_id]["month"]
                year = user_data[chat_id]["year"]
                
                if text == "Весь месяц":
                    send_monthly_report(chat_id, month, year)
                    del user_data[chat_id]
                    send_reports_menu(chat_id)
                elif " " in text and text.split(" ")[0].isdigit():
                    # Парсим неделю: "1-7 Июнь" или "29-30 Июнь" УЧИТЫВАЕМ ВТОРУЮ НЕДЕЛЮ ЗА. ДЕНЛ 
                    week_part = text.split(" ")[0]
                    if "-" in week_part:
                        start, end = map(int, week_part.split("-"))
                        send_monthly_report(chat_id, month, year, (start, end))
                        del user_data[chat_id]
                        send_reports_menu(chat_id)
                    else:
                        send_message(chat_id, "❌ Ошибка формата")
                else:
                    send_message(chat_id, "❌ Пожалуйста, выберите неделю из меню")
            
            # ---- ОБРАБОТКА КОЛИЧЕСТВА ----
            elif chat_id in user_data and user_data[chat_id].get("waiting_for") == "quantity":
                try:
                    quantity = float(text.replace(",", "."))
                    product = user_data[chat_id]["product"]
                    success, loss = save_to_sheet(user_name, product, quantity)
                    if success:
                        send_message(chat_id, f"✅ Списано: {product} — {quantity} шт\n💰 Сумма списаний: {loss:.0f} ₸")
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
                    success, loss = save_to_sheet(user_name, product, quantity)
                    if success:
                        send_message(chat_id, f"✅ Списано: {product} — {quantity} шт\n💰 Сумма списаний: {loss:.0f} ₸")
                    else:
                        send_message(chat_id, "❌ Ошибка сохранения в таблицу")
                    del user_data[chat_id]
                    send_main_menu(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ Введите число, например: 2 или 1.5")
            
            elif text == "➕ Другое":
                user_data[chat_id] = {"waiting_for": "other_product"}
                send_message(chat_id, "✏️ Напишите название позиции:")
            
            elif text == "◀️ Назад":
                # Определяем откуда пришли
                if chat_id in user_data and "waiting_for" in user_data[chat_id]:
                    # Если были в процессе выбора месяца/недели, возвращаем в меню отчётов
                    if user_data[chat_id].get("waiting_for") in ["week_in_month"]:
                        del user_data[chat_id]
                        send_reports_menu(chat_id)
                    else:
                        # Обычное меню продукта
                        send_main_menu(chat_id)
                else:
                    send_main_menu(chat_id)
            
            else:
                send_message(chat_id, "❌ Используйте кнопки меню")
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/', methods=['GET'])
def index():
    return "Бот работает с ценами и отчётами по месяцам!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)