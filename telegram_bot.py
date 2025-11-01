# telegram_bot.py
"""
Головний Telegram бот для моніторингу електропостачання
"""

import threading
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import TG_TOKEN, CHAT_ID, POLL_INTERVAL
from yasno_parser import YasnoParser
from tuya_monitor import TuyaMonitor


class PowerMonitorBot:
    """Telegram бот для моніторингу електропостачання"""
    
    def __init__(self):
        self.app = Application.builder().token(TG_TOKEN).build()
        self.yasno = YasnoParser()
        self.tuya = TuyaMonitor()
        
        # Реєструємо обробники
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("schedule", self.cmd_schedule))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Встановлюємо callback для Tuya
        self.tuya.set_on_status_change(self.on_power_change)
    
    def get_keyboard(self):
        """Створює клавіатуру з кнопками"""
        keyboard = [
            [
                InlineKeyboardButton("📊 Переглянути графік", callback_data="schedule"),
                InlineKeyboardButton("🔌 Статус розетки", callback_data="status")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def send_message(self, text, show_buttons=True):
        """Відправляє повідомлення в Telegram"""
        try:
            if show_buttons:
                await self.app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    reply_markup=self.get_keyboard()
                )
            else:
                await self.app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text
                )
        except Exception as e:
            print(f"❌ Помилка відправки повідомлення: {e}")
    
    def on_power_change(self, has_power, duration_seconds):
        """
        Callback викликається при зміні статусу світла
        
        Args:
            has_power: True - світло з'явилось, False - світло зникло
            duration_seconds: тривалість попереднього стану
        """
        # Форматуємо повідомлення
        now_str = datetime.now().strftime("%H:%M")
        duration_text = self.tuya.format_duration(duration_seconds)
        
        if has_power:
            # Світло з'явилось
            emoji = "🟢"
            status_text = "Світло З'ЯВИЛОСЬ!"
            duration_info = f"⏱ Світла не було {duration_text}"
            outage_type = ""
        else:
            # Світло зникло
            emoji = "🔴"
            status_text = "Світла немає"
            duration_info = f"⏱ Світло було {duration_text}"
            
            # Перевіряємо чи це планове відключення
            self.yasno.fetch_schedule()
            is_planned, end_time = self.yasno.is_outage_planned()
            
            if is_planned:
                outage_type = f"\n📋 Відключення за графіком Yasno"
                if end_time:
                    outage_type += f"\n⏰ Очікується відновлення о {end_time}"
            else:
                outage_type = "\n⚠️ Аварійне відключення (не за графіком)"
        
        message = f"{emoji} {now_str} {status_text}\n{duration_info}{outage_type}"
        
        # Відправляємо повідомлення (синхронний виклик)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        loop.run_until_complete(self.send_message(message, show_buttons=True))
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /start"""
        welcome_text = (
            "👋 Вітаю! Я бот для моніторингу електропостачання.\n\n"
            "Я автоматично відстежую:\n"
            "• 🔌 Статус розетки (кожні 5 сек)\n"
            "• 📊 Графік відключень YASNO\n"
            "• ⚡ Тип відключення (планове/аварійне)\n\n"
            "Команди:\n"
            "/status - поточний статус розетки\n"
            "/schedule - графік відключень\n\n"
            "Або використовуйте кнопки нижче 👇"
        )
        await update.message.reply_text(welcome_text, reply_markup=self.get_keyboard())
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /status"""
        info = self.tuya.get_status_info()
        
        if info['has_power'] is None:
            text = "❌ Не вдалося отримати статус розетки"
        else:
            emoji = "🟢" if info['has_power'] else "🔴"
            status_text = "Світло Є" if info['has_power'] else "Світла немає"
            text = (
                f"{emoji} {info['timestamp']} {status_text}\n"
                f"⏱ У цьому стані: {info['duration_text']}"
            )
            
            # Якщо світла немає, перевіряємо графік
            if not info['has_power']:
                self.yasno.fetch_schedule()
                is_planned, end_time = self.yasno.is_outage_planned()
                
                if is_planned:
                    text += f"\n📋 Відключення за графіком Yasno"
                    if end_time:
                        text += f"\n⏰ Очікується до {end_time}"
                else:
                    text += "\n⚠️ Аварійне відключення"
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
        else:
            await update.message.reply_text(text, reply_markup=self.get_keyboard())
    
    async def cmd_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /schedule"""
        if not self.yasno.fetch_schedule():
            text = "❌ Не вдалося завантажити графік відключень"
        else:
            text = self.yasno.get_full_schedule_text()
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
        else:
            await update.message.reply_text(text, reply_markup=self.get_keyboard())
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник натискань на кнопки"""
        query = update.callback_query
        
        if query.data == "status":
            await self.cmd_status(update, context)
        elif query.data == "schedule":
            await self.cmd_schedule(update, context)
    
    def start_tuya_monitoring(self):
        """Запускає моніторинг Tuya в окремому потоці"""
        thread = threading.Thread(target=self.tuya.start_monitoring, args=(POLL_INTERVAL,), daemon=True)
        thread.start()
        print("✅ Моніторинг Tuya запущено в фоновому режимі")
    
    def run(self):
        """Запускає бота"""
        print("🚀 Запуск бота...")
        
        # Завантажуємо початковий графік
        self.yasno.fetch_schedule()
        
        # Запускаємо моніторинг Tuya
        self.start_tuya_monitoring()
        
        # Запускаємо бота
        print("✅ Бот запущено! Натисніть Ctrl+C для зупинки.")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = PowerMonitorBot()
    bot.run()
