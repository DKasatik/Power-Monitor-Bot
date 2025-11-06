# database.py
"""
Менеджер бази даних для Power Monitor Bot
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
from contextlib import contextmanager


class DatabaseManager:
    """Менеджер для роботи з PostgreSQL базою даних"""
    
    def __init__(self):
        self.db_config = {
            'host': os.getenv('DB_HOST', 'postgres'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'power_monitor'),
            'user': os.getenv('DB_USER', 'powerbot'),
            'password': os.getenv('DB_PASSWORD', 'powerbot_secure_pass_2024')
        }
        self._test_connection()
    
    def _test_connection(self):
        """Перевіряє з'єднання з базою даних"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1')
            print("✅ З'єднання з базою даних успішне")
        except Exception as e:
            print(f"❌ Помилка з'єднання з базою даних: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager для з'єднання з БД"""
        conn = psycopg2.connect(**self.db_config)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def save_power_event(self, has_power, duration_seconds, is_planned=False, 
                        expected_end_time=None, yasno_schedule=None):
        """
        Зберігає подію зміни стану електроенергії
        
        Args:
            has_power: True якщо світло з'явилось, False якщо зникло
            duration_seconds: тривалість попереднього стану
            is_planned: чи було відключення за графіком
            expected_end_time: очікуваний час відновлення (формат HH:MM)
            yasno_schedule: текст графіка Yasno
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO power_events 
                        (event_time, has_power, duration_seconds, is_planned, 
                         expected_end_time, yasno_schedule)
                        VALUES (NOW(), %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (has_power, duration_seconds, is_planned, 
                          expected_end_time, yasno_schedule))
                    
                    event_id = cur.fetchone()[0]
                    print(f"✅ Подія збережена (ID: {event_id})")
                    return event_id
        except Exception as e:
            print(f"❌ Помилка збереження події: {e}")
            return None
    
    def update_current_state(self, has_power):
        """
        Оновлює поточний стан системи
        
        Args:
            has_power: поточний стан електроенергії
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE current_state 
                        SET has_power = %s, 
                            last_change_time = NOW(),
                            updated_at = NOW()
                        WHERE id = 1
                    """, (has_power,))
                    print(f"✅ Поточний стан оновлено: {'Є світло' if has_power else 'Немає світла'}")
        except Exception as e:
            print(f"❌ Помилка оновлення стану: {e}")
    
    def get_current_state(self):
        """
        Отримує поточний стан з бази даних
        
        Returns:
            dict: {has_power, last_change_time} або None
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT has_power, last_change_time 
                        FROM current_state 
                        WHERE id = 1
                    """)
                    return cur.fetchone()
        except Exception as e:
            print(f"❌ Помилка отримання стану: {e}")
            return None
    
    def get_recent_events(self, limit=10):
        """
        Отримує останні події
        
        Args:
            limit: кількість подій
            
        Returns:
            list: список подій
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT 
                            event_time AT TIME ZONE 'Europe/Kiev' as event_time,
                            has_power,
                            duration_seconds,
                            is_planned,
                            expected_end_time
                        FROM power_events
                        ORDER BY event_time DESC
                        LIMIT %s
                    """, (limit,))
                    return cur.fetchall()
        except Exception as e:
            print(f"❌ Помилка отримання історії: {e}")
            return []
    
    def get_daily_statistics(self, days=7):
        """
        Отримує статистику за останні N днів
        
        Args:
            days: кількість днів
            
        Returns:
            list: статистика по днях
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT 
                            stat_date,
                            total_outages,
                            planned_outages,
                            emergency_outages,
                            total_outage_duration_seconds,
                            longest_outage_seconds
                        FROM power_statistics
                        WHERE stat_date >= CURRENT_DATE - INTERVAL '%s days'
                        ORDER BY stat_date DESC
                    """, (days,))
                    return cur.fetchall()
        except Exception as e:
            print(f"❌ Помилка отримання статистики: {e}")
            return []
    
    def get_today_statistics(self):
        """
        Отримує статистику за сьогодні
        
        Returns:
            dict: статистика або None
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT 
                            total_outages,
                            planned_outages,
                            emergency_outages,
                            total_outage_duration_seconds,
                            longest_outage_seconds
                        FROM power_statistics
                        WHERE stat_date = CURRENT_DATE
                    """)
                    return cur.fetchone()
        except Exception as e:
            print(f"❌ Помилка отримання статистики: {e}")
            return None
    
    def format_duration(self, seconds):
        """
        Форматує тривалість у читабельний вигляд
        
        Args:
            seconds: кількість секунд
            
        Returns:
            str: відформатована тривалість
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours} год. {minutes} хв."
        else:
            return f"{minutes} хв."


if __name__ == "__main__":
    # Тест
    db = DatabaseManager()
    
    # Тестуємо збереження події
    event_id = db.save_power_event(
        has_power=False,
        duration_seconds=3600,
        is_planned=True,
        expected_end_time="18:00",
        yasno_schedule="Тестовий графік"
    )
    
    # Оновлюємо стан
    db.update_current_state(False)
    
    # Отримуємо останні події
    events = db.get_recent_events(5)
    print(f"\n📋 Останні {len(events)} подій:")
    for event in events:
        print(f"  - {event['event_time']}: {'🟢' if event['has_power'] else '🔴'}")
    
    # Отримуємо статистику
    stats = db.get_today_statistics()
    if stats:
        print(f"\n📊 Статистика за сьогодні:")
        print(f"  Всього відключень: {stats['total_outages']}")
        print(f"  Планових: {stats['planned_outages']}")
        print(f"  Аварійних: {stats['emergency_outages']}")
