# tuya_monitor.py
"""
Монітор статусу розетки Tuya
"""

import time
from datetime import datetime
from tuya_connector import TuyaOpenAPI
from config import ACCESS_ID, ACCESS_KEY, DEVICE_ID, ENDPOINT, POLL_INTERVAL


class TuyaMonitor:
    """Монітор розетки Tuya з відстеженням змін статусу"""
    
    def __init__(self):
        self.openapi = TuyaOpenAPI(ENDPOINT, ACCESS_ID, ACCESS_KEY)
        self.openapi.connect()
        
        self.last_status = None
        self.last_change_time = datetime.now()
        self.on_status_change_callback = None
    
    def set_on_status_change(self, callback):
        """
        Встановлює callback-функцію, яка викликається при зміні статусу
        
        Args:
            callback: функція з сигнатурою callback(has_power: bool, duration_seconds: int)
        """
        self.on_status_change_callback = callback
    
    def get_current_status(self):
        """
        Отримує поточний статус розетки
        
        Returns:
            bool або None: True - світло є, False - світла немає, None - помилка
        """
        try:
            response = self.openapi.get(f"/v1.0/devices/{DEVICE_ID}/status")
            
            for item in response.get("result", []):
                if item["code"] == "switch_1":
                    return item["value"]
            
            print("❌ Помилка: не знайдено switch_1")
            return None
            
        except Exception as e:
            print(f"❌ Помилка при отриманні статусу: {e}")
            return None
    
    def get_status_duration(self):
        """
        Повертає тривалість поточного статусу
        
        Returns:
            int: кількість секунд
        """
        return int((datetime.now() - self.last_change_time).total_seconds())
    
    def format_duration(self, seconds):
        """
        Форматує тривалість у читабельний вигляд
        
        Args:
            seconds: кількість секунд
        
        Returns:
            str: відформатована тривалість (наприклад "2 год. 10 хв.")
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours} год. {minutes} хв."
        else:
            return f"{minutes} хв."
    
    def check_status(self):
        """
        Перевіряє статус і викликає callback при зміні
        
        Returns:
            bool: True якщо статус змінився, False якщо ні
        """
        current_status = self.get_current_status()
        
        if current_status is None:
            return False
        
        # Ініціалізація при першому запуску
        if self.last_status is None:
            self.last_status = current_status
            self.last_change_time = datetime.now()
            return False
        
        # Перевірка зміни статусу
        if current_status != self.last_status:
            duration_seconds = self.get_status_duration()
            
            # Викликаємо callback
            if self.on_status_change_callback:
                self.on_status_change_callback(current_status, duration_seconds)
            
            # Оновлюємо статус
            self.last_status = current_status
            self.last_change_time = datetime.now()
            
            return True
        
        return False
    
    def get_status_info(self):
        """
        Повертає повну інформацію про поточний статус
        
        Returns:
            dict: {
                'has_power': bool,
                'duration_seconds': int,
                'duration_text': str,
                'timestamp': str
            }
        """
        duration_seconds = self.get_status_duration()
        
        return {
            'has_power': self.last_status,
            'duration_seconds': duration_seconds,
            'duration_text': self.format_duration(duration_seconds),
            'timestamp': datetime.now().strftime("%H:%M")
        }
    
    def start_monitoring(self, interval=POLL_INTERVAL):
        """
        Запускає безкінечний цикл моніторингу (блокуючий)
        
        Args:
            interval: інтервал перевірки в секундах
        """
        print(f"🔍 Запущено моніторинг розетки (інтервал: {interval} сек)")
        
        while True:
            try:
                self.check_status()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n⏹ Моніторинг зупинено")
                break
            except Exception as e:
                print(f"❌ Помилка в циклі моніторингу: {e}")
                time.sleep(interval)


if __name__ == "__main__":
    # Тест
    def on_change(has_power, duration):
        if has_power:
            print(f"🟢 Світло з'явилось! Не було {duration} сек")
        else:
            print(f"🔴 Світло зникло! Було {duration} сек")
    
    monitor = TuyaMonitor()
    monitor.set_on_status_change(on_change)
    monitor.start_monitoring()
