import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- НАСТРОЙКИ (из переменных окружения) ---
# Токен вы получите у @BotFather. Позже поместим его в секреты Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не задан!")

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопки при команде /start"""
    keyboard = [
        [InlineKeyboardButton("🥐 Списать круассан", callback_data="croissant")],
        [InlineKeyboardButton("🥪 Списать панини", callback_data="panini")],
        [InlineKeyboardButton("➕ Другое", callback_data="other")],
        [InlineKeyboardButton("📊 Отчет за неделю", callback_data="report")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🍽 **Кофейный бот учета**\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на кнопки"""
    query = update.callback_query
    await query.answer()  # Обязательно отвечаем, чтобы убрать "часики"

    data = query.data
    user = query.from_user.first_name

    if data == "croissant":
        # Показываем меню круассанов
        kb = [
            [InlineKeyboardButton("🥐 Ветчина/сыр", callback_data="sp_croissant_ham")],
            [InlineKeyboardButton("🥐 Лосось/сыр", callback_data="sp_croissant_salmon")],
            [InlineKeyboardButton("🥐 Нутелла", callback_data="sp_croissant_nutella")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")],
        ]
        await query.edit_message_text("Выберите КРУАССАН:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "panini":
        # Показываем меню панини
        kb = [
            [InlineKeyboardButton("🥪 Курица/грибы", callback_data="sp_panini_chicken")],
            [InlineKeyboardButton("🥪 Прошутто", callback_data="sp_panini_prosciutto")],
            [InlineKeyboardButton("🥪 Тунец", callback_data="sp_panini_tuna")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")],
        ]
        await query.edit_message_text("Выберите ПАНИНИ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "report":
        # Здесь мы позже сделаем настоящий отчет из таблицы
        await query.edit_message_text("📊 Отчет за неделю:\nКруассаны: 15 шт\nПанини: 8 шт")
    elif data.startswith("sp_"):
        # Сохраняем списание (пока просто в логи, потом заменим на Google Sheets)
        product = data.split("_", 2)[2].replace("_", " ").capitalize()
        logger.info(f"✅ СПИСАНО: {user} -> {product} в {datetime.now()}")
        await query.edit_message_text(f"✅ Списано: {product}\n\nСпасибо! Используйте /start для новых списаний.")
    elif data == "back":
        await start(update, context)  # Возвращаем стартовое меню

# --- Flask для приема вебхуков ---
# Это "мостик", который принимает запросы от Telegram и передает их боту
app = Flask(__name__)
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()

# Регистрируем команды
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
async def webhook():
    """Telegram присылает сюда обновления"""
    try:
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        await telegram_app.process_update(update)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"status": "error"}), 500

# Запуск сервера
if __name__ == "__main__":
    # Устанавливаем вебхук при старте
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(telegram_app.bot.set_webhook(
        url=f"https://YOUR_APP_NAME.onrender.com/webhook/{TELEGRAM_TOKEN}"
    ))
    logger.info("🚀 Бот запущен на порту 5000")
    app.run(host="0.0.0.0", port=5000)