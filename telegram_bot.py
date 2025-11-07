# telegram_bot.py
"""
Головний Telegram бот для моніторингу електропостачання з PostgreSQL та розкладом
"""

import threading
from datetime import datetime, time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TG_TOKEN, CHAT_ID, POLL_INTERVAL
from yasno_parser import YasnoParser
from tuya_monitor import TuyaMonitor
from database import DatabaseManager

# Український часовий пояс
KYIV_TZ = pytz.timezone('Europe/Kiev')

# Нічний режим (тихі повідомлення)
NIGHT_START = time(23, 0)  # 23:00
NIGHT_END = time(6, 0)     # 06:00


class PowerMonitorBot:
    """Telegram бот для моніторингу електропостачання"""
    
    def __init__(self):
        self.app = Application.builder().token(TG_TOKEN).build()
        self.yasno = YasnoParser()
        self.tuya = TuyaMonitor()
        self.db = DatabaseManager()
        self.scheduler = AsyncIOScheduler(timezone=KYIV_TZ)
        
        # Реєструємо обробники
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("schedule", self.cmd_schedule))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("history", self.cmd_history))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Встановлюємо callback для Tuya
        self.tuya.set_on_status_change(self.on_power_change)
        
        # Налаштовуємо розклад повідомлень
        self._setup_scheduled_tasks()
    
    def _setup_scheduled_tasks(self):
        """Налаштовує розклад автоматичних повідомлень"""
        
        # Щоденний графік о 6:15
        self.scheduler.add_job(
            self.send_daily_schedule,
            CronTrigger(hour=6, minute=15, timezone=KYIV_TZ),
            id='daily_schedule',
            name='Щоденний графік відключень'
        )
        
        # Тижнева статистика (понеділок о 9:00)
        self.scheduler.add_job(
            self.send_weekly_stats,
            CronTrigger(day_of_week='mon', hour=9, minute=0, timezone=KYIV_TZ),
            id='weekly_stats',
            name='Тижнева статистика'
        )
        
        # Місячна статистика (1-го числа о 9:00)
        self.scheduler.add_job(
            self.send_monthly_stats,
            CronTrigger(day=1, hour=9, minute=0, timezone=KYIV_TZ),
            id='monthly_stats',
            name='Місячна статистика'
        )
        
        print("✅ Розклад повідомлень налаштовано:")
        print("   📅 Щоденний графік: 6:15")
        print("   📊 Тижнева статистика: Понеділок 9:00")
        print("   📈 Місячна статистика: 1-го числа 9:00")
    
    def is_night_time(self):
        """Перевіряє чи зараз нічний час"""
        current_time = self.get_kyiv_time().time()
        
        if NIGHT_START > NIGHT_END:  # Через північ (23:00 - 06:00)
            return current_time >= NIGHT_START or current_time < NIGHT_END
        else:
            return NIGHT_START <= current_time < NIGHT_END
    
    def get_kyiv_time(self):
        """Повертає поточний час у київському часовому поясі"""
        return datetime.now(KYIV_TZ)
    
    def get_keyboard(self):
        """Створює клавіатуру з кнопками"""
        keyboard = [
            [
                InlineKeyboardButton("📊 Графік", callback_data="schedule"),
                InlineKeyboardButton("🔌 Статус", callback_data="status")
            ],
            [
                InlineKeyboardButton("📈 Статистика", callback_data="stats"),
                InlineKeyboardButton("📜 Історія", callback_data="history")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def send_message(self, text, show_buttons=True, silent=False):
        """
        Відправляє повідомлення в Telegram
        
        Args:
            text: текст повідомлення
            show_buttons: чи показувати кнопки
            silent: тихе повідомлення (без звуку)
        """
        try:
            if show_buttons:
                await self.app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    reply_markup=self.get_keyboard(),
                    disable_notification=silent
                )
            else:
                await self.app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    disable_notification=silent
                )
        except Exception as e:
            print(f"❌ Помилка відправки повідомлення: {e}")
    
    async def send_daily_schedule(self):
        """Надсилає щоденний графік відключень о 6:15"""
        print("📅 Надсилаю щоденний графік...")
        
        if not self.yasno.fetch_schedule():
            text = "☀️ Доброго ранку!\n\n❌ Не вдалося завантажити графік відключень"
        else:
            schedule_text = self.yasno.get_schedule_text("today")
            text = f"☀️ Доброго ранку!\n\n{schedule_text}"
        
        await self.send_message(text, show_buttons=True, silent=False)
    
    async def send_weekly_stats(self):
        """Надсилає тижневу статистику (понеділок о 9:00)"""
        print("📊 Надсилаю тижневу статистику...")
        
        week_stats = self.db.get_daily_statistics(7)
        
        if not week_stats:
            text = "📊 Тижнева статистика\n\nДаних за минулий тиждень немає."
            await self.send_message(text, show_buttons=True, silent=False)
            return
        
        total_outages = sum(s['total_outages'] for s in week_stats)
        total_planned = sum(s['planned_outages'] for s in week_stats)
        total_emergency = sum(s['emergency_outages'] for s in week_stats)
        total_duration = sum(s['total_outage_duration_seconds'] for s in week_stats)
        
        avg_duration = total_duration // total_outages if total_outages > 0 else 0
        
        text = "📊 Статистика за тиждень\n"
        text += f"📅 {week_stats[-1]['stat_date'].strftime('%d.%m')} - {week_stats[0]['stat_date'].strftime('%d.%m.%Y')}\n\n"
        text += f"⚡ Всього відключень: {total_outages}\n"
        text += f"📋 Планових: {total_planned}\n"
        text += f"⚠️ Аварійних: {total_emergency}\n\n"
        text += f"⏱ Загальний час без світла: {self.db.format_duration(total_duration)}\n"
        text += f"📊 Середня тривалість: {self.db.format_duration(avg_duration)}\n\n"
        
        # Найгірший день
        worst_day = max(week_stats, key=lambda x: x['total_outage_duration_seconds'])
        if worst_day['total_outages'] > 0:
            text += f"🔴 Найгірший день: {worst_day['stat_date'].strftime('%d.%m')} "
            text += f"({worst_day['total_outages']} відкл., {self.db.format_duration(worst_day['total_outage_duration_seconds'])})"
        
        await self.send_message(text, show_buttons=True, silent=False)
    
    async def send_monthly_stats(self):
        """Надсилає місячну статистику (1-го числа о 9:00)"""
        print("📈 Надсилаю місячну статистику...")
        
        month_stats = self.db.get_daily_statistics(30)
        
        if not month_stats:
            text = "📈 Місячна статистика\n\nДаних за минулий місяць немає."
            await self.send_message(text, show_buttons=True, silent=False)
            return
        
        total_outages = sum(s['total_outages'] for s in month_stats)
        total_planned = sum(s['planned_outages'] for s in month_stats)
        total_emergency = sum(s['emergency_outages'] for s in month_stats)
        total_duration = sum(s['total_outage_duration_seconds'] for s in month_stats)
        
        avg_duration = total_duration // total_outages if total_outages > 0 else 0
        days_with_outages = sum(1 for s in month_stats if s['total_outages'] > 0)
        
        text = "📈 Статистика за місяць\n"
        text += f"📅 {month_stats[-1]['stat_date'].strftime('%B %Y')}\n\n"
        text += f"⚡ Всього відключень: {total_outages}\n"
        text += f"📋 Планових: {total_planned}\n"
        text += f"⚠️ Аварійних: {total_emergency}\n\n"
        text += f"📆 Днів з відключеннями: {days_with_outages} з {len(month_stats)}\n"
        text += f"⏱ Загальний час без світла: {self.db.format_duration(total_duration)}\n"
        text += f"📊 Середня тривалість: {self.db.format_duration(avg_duration)}\n\n"
        
        # Найгірший день
        worst_day = max(month_stats, key=lambda x: x['total_outage_duration_seconds'])
        if worst_day['total_outages'] > 0:
            text += f"🔴 Найгірший день: {worst_day['stat_date'].strftime('%d.%m')} "
            text += f"({worst_day['total_outages']} відкл., {self.db.format_duration(worst_day['total_outage_duration_seconds'])})"
        
        await self.send_message(text, show_buttons=True, silent=False)
    
    def on_power_change(self, has_power, duration_seconds):
        """
        Callback викликається при зміні статусу світла
        
        Args:
            has_power: True - світло з'явилось, False - світло зникло
            duration_seconds: тривалість попереднього стану
        """
        # Форматуємо повідомлення з українським часом
        now_str = self.get_kyiv_time().strftime("%H:%M")
        duration_text = self.tuya.format_duration(duration_seconds)
        
        # Перевіряємо чи це планове відключення
        self.yasno.fetch_schedule()
        is_planned, end_time = self.yasno.is_outage_planned()
        yasno_schedule = self.yasno.get_full_schedule_text() if not has_power else None
        
        # Зберігаємо подію в БД
        self.db.save_power_event(
            has_power=has_power,
            duration_seconds=duration_seconds,
            is_planned=is_planned if not has_power else False,
            expected_end_time=end_time,
            yasno_schedule=yasno_schedule
        )
        
        # Оновлюємо поточний стан
        self.db.update_current_state(has_power)
        
        # Визначаємо чи тихе повідомлення
        is_silent = self.is_night_time()
        night_indicator = " 🌙" if is_silent else ""
        
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
            
            if is_planned:
                outage_type = f"\n📋 Відключення за графіком Yasno"
                if end_time:
                    outage_type += f"\n⏰ Очікується відновлення о {end_time}"
            else:
                outage_type = "\n⚠️ Аварійне відключення (не за графіком)"
        
        message = f"{emoji} {now_str} {status_text}{night_indicator}\n{duration_info}{outage_type}"
        
        # Відправляємо повідомлення (синхронний виклик)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        loop.run_until_complete(self.send_message(message, show_buttons=True, silent=is_silent))
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /start"""
        welcome_text = (
            "👋 Вітаю! Я бот для моніторингу електропостачання.\n\n"
            "Я автоматично відстежую:\n"
            "• 🔌 Статус розетки (кожні 5 сек)\n"
            "• 📊 Графік відключень YASNO\n"
            "• ⚡ Тип відключення (планове/аварійне)\n"
            "• 📈 Статистику відключень\n\n"
            "📅 Автоматичні повідомлення:\n"
            "• 6:15 - щоденний графік\n"
            "• Понеділок 9:00 - тижнева статистика\n"
            "• 1-го числа 9:00 - місячна статистика\n\n"
            "🌙 Нічний режим (23:00-6:00) - тихі сповіщення\n\n"
            "Команди:\n"
            "/status - поточний статус\n"
            "/schedule - графік відключень\n"
            "/stats - статистика\n"
            "/history - історія подій\n\n"
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
            kyiv_time = self.get_kyiv_time().strftime("%H:%M")
            text = (
                f"{emoji} {kyiv_time} {status_text}\n"
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
            try:
                await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"⚠️ Помилка редагування: {e}")
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
            try:
                await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"⚠️ Помилка редагування: {e}")
        else:
            await update.message.reply_text(text, reply_markup=self.get_keyboard())
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /stats - статистика відключень"""
        today_stats = self.db.get_today_statistics()
        week_stats = self.db.get_daily_statistics(7)
        
        text = "📈 Статистика відключень\n\n"
        
        # Сьогоднішня статистика
        if today_stats and today_stats['total_outages'] > 0:
            text += f"📅 Сьогодні ({self.get_kyiv_time().strftime('%d.%m.%Y')}):\n"
            text += f"  • Всього відключень: {today_stats['total_outages']}\n"
            text += f"  • Планових: {today_stats['planned_outages']}\n"
            text += f"  • Аварійних: {today_stats['emergency_outages']}\n"
            text += f"  • Загальна тривалість: {self.db.format_duration(today_stats['total_outage_duration_seconds'])}\n"
            text += f"  • Найдовше: {self.db.format_duration(today_stats['longest_outage_seconds'])}\n\n"
        else:
            text += "📅 Сьогодні відключень не було ✅\n\n"
        
        # Тижнева статистика
        if week_stats:
            text += "📊 За останні 7 днів:\n"
            total_outages = sum(s['total_outages'] for s in week_stats)
            total_planned = sum(s['planned_outages'] for s in week_stats)
            total_emergency = sum(s['emergency_outages'] for s in week_stats)
            
            text += f"  • Всього відключень: {total_outages}\n"
            text += f"  • Планових: {total_planned}\n"
            text += f"  • Аварійних: {total_emergency}\n"
        
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"⚠️ Помилка редагування: {e}")
        else:
            await update.message.reply_text(text, reply_markup=self.get_keyboard())
    
    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /history - історія подій"""
        events = self.db.get_recent_events(10)
        
        if not events:
            text = "📜 Історія подій порожня"
        else:
            text = "📜 Останні 10 подій:\n\n"
            
            for event in events:
                emoji = "🟢" if event['has_power'] else "🔴"
                status = "Світло є" if event['has_power'] else "Світла немає"
                time_str = event['event_time'].strftime("%d.%m %H:%M")
                duration = self.db.format_duration(event['duration_seconds'])
                
                event_type = ""
                if not event['has_power']:
                    if event['is_planned']:
                        event_type = " (📋 планове"
                        if event['expected_end_time']:
                            event_type += f", до {event['expected_end_time']}"
                        event_type += ")"
                    else:
                        event_type = " (⚠️ аварійне)"
                
                text += f"{emoji} {time_str} - {status}\n"
                text += f"   Тривало: {duration}{event_type}\n\n"
        
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(text, reply_markup=self.get_keyboard())
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"⚠️ Помилка редагування: {e}")
        else:
            await update.message.reply_text(text, reply_markup=self.get_keyboard())
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник натискань на кнопки"""
        query = update.callback_query
        
        if query.data == "status":
            await self.cmd_status(update, context)
        elif query.data == "schedule":
            await self.cmd_schedule(update, context)
        elif query.data == "stats":
            await self.cmd_stats(update, context)
        elif query.data == "history":
            await self.cmd_history(update, context)
    
    def start_tuya_monitoring(self):
        """Запускає моніторинг Tuya в окремому потоці"""
        thread = threading.Thread(target=self.tuya.start_monitoring, args=(POLL_INTERVAL,), daemon=True)
        thread.start()
        print("✅ Моніторинг Tuya запущено в фоновому режимі")
    
    def run(self):
        """Запускає бота"""
        print("🚀 Запуск бота...")
        print(f"🕐 Поточний час (Київ): {self.get_kyiv_time().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🌙 Нічний режим: {NIGHT_START.strftime('%H:%M')} - {NIGHT_END.strftime('%H:%M')}")
        
        # Завантажуємо початковий графік
        self.yasno.fetch_schedule()
        
        # Запускаємо моніторинг Tuya
        self.start_tuya_monitoring()
        
        # Додаємо callback для запуску scheduler після створення event loop
        async def post_init(application):
            self.scheduler.start()
            print("✅ Scheduler запущено")
        
        self.app.post_init = post_init
        
        # Запускаємо бота
        print("✅ Бот запущено! Натисніть Ctrl+C для зупинки.")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = PowerMonitorBot()
    bot.run()