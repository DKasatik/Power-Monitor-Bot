# yasno_parser.py
"""
Парсер графіків відключень світла YASNO
"""

import requests
from datetime import datetime
from config import YASNO_GROUP, YASNO_REGION, YASNO_DSO


class YasnoParser:
    """Парсер графіків відключень світла YASNO"""
    
    def __init__(self, group=YASNO_GROUP):
        self.group = group
        self.data = None
        self.api_url = f"https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{YASNO_REGION}/dsos/{YASNO_DSO}/planned-outages"
    
    def fetch_schedule(self):
        """Отримує дані з API YASNO"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(self.api_url, headers=headers, timeout=10)
            response.raise_for_status()
            self.data = response.json()
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Помилка при завантаженні даних: {e}")
            return False
    
    def minutes_to_time(self, minutes):
        """Конвертує хвилини від початку доби в формат HH:MM"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"
    
    def get_today_schedule(self):
        """Отримує графік на сьогодні для вказаної групи"""
        if not self.data:
            return None
        
        group_data = self.data.get(self.group)
        if not group_data:
            print(f"❌ Дані для групи {self.group} не знайдено")
            return None
        
        return group_data.get("today")
    
    def get_tomorrow_schedule(self):
        """Отримує графік на завтра для вказаної групи"""
        if not self.data:
            return None
        
        group_data = self.data.get(self.group)
        if not group_data:
            return None
        
        return group_data.get("tomorrow")
    
    def is_outage_planned(self, check_time=None):
        """
        Перевіряє чи є відключення запланованим на вказаний час
        
        Args:
            check_time: datetime об'єкт (за замовчуванням - зараз)
        
        Returns:
            tuple: (is_planned, end_time_str або None)
        """
        if check_time is None:
            check_time = datetime.now()
        
        schedule = self.get_today_schedule()
        if not schedule:
            return False, None
        
        current_minutes = check_time.hour * 60 + check_time.minute
        slots = schedule.get("slots", [])
        
        for slot in slots:
            if slot.get("type") == "Definite":
                if slot["start"] <= current_minutes < slot["end"]:
                    return True, self.minutes_to_time(slot["end"])
        
        return False, None
    
    def get_schedule_text(self, day="today"):
        """
        Формує текстове повідомлення з графіком
        
        Args:
            day: "today" або "tomorrow"
        
        Returns:
            str: Відформатований текст графіка
        """
        if day == "today":
            schedule = self.get_today_schedule()
            date_label = "сьогодні"
        else:
            schedule = self.get_tomorrow_schedule()
            date_label = "завтра"
        
        if not schedule:
            return f"❌ Графік на {date_label} не знайдено"
        
        # Парсимо дату
        date_str = schedule.get("date", "")
        try:
            date_obj = datetime.fromisoformat(date_str.replace('+02:00', ''))
            day_name = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"][date_obj.weekday()]
            formatted_date = date_obj.strftime("%d.%m")
        except:
            day_name = "Невідомо"
            formatted_date = ""
        
        # Фільтруємо тільки заплановані відключення (type="Definite")
        slots = schedule.get("slots", [])
        planned_outages = [slot for slot in slots if slot.get("type") == "Definite"]
        
        result = f"🔌 Графік на {date_label} ({day_name}, {formatted_date}):\n\n"
        
        if not planned_outages:
            result += "✅ Запланованих відключень немає"
        else:
            for slot in planned_outages:
                start_time = self.minutes_to_time(slot["start"])
                end_time = self.minutes_to_time(slot["end"])
                result += f"⚡ {start_time} — {end_time}\n"
        
        return result.strip()
    
    def get_full_schedule_text(self):
        """Отримує повний графік на сьогодні та завтра"""
        today = self.get_schedule_text("today")
        tomorrow = self.get_schedule_text("tomorrow")
        return f"{today}\n\n{tomorrow}"


if __name__ == "__main__":
    # Тест
    parser = YasnoParser()
    if parser.fetch_schedule():
        print(parser.get_full_schedule_text())
        is_planned, end_time = parser.is_outage_planned()
        print(f"\nЗараз планове відключення: {is_planned}")
        if end_time:
            print(f"Очікується до {end_time}")
    else:
        print("Не вдалося завантажити дані")
