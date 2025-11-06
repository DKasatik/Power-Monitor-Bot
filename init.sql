-- init.sql
-- Ініціалізація бази даних для Power Monitor Bot

-- Таблиця подій (всі зміни стану електроенергії)
CREATE TABLE IF NOT EXISTS power_events (
    id SERIAL PRIMARY KEY,
    event_time TIMESTAMP NOT NULL DEFAULT NOW(),
    has_power BOOLEAN NOT NULL,
    duration_seconds INTEGER NOT NULL,
    is_planned BOOLEAN DEFAULT FALSE,
    expected_end_time TIME,
    yasno_schedule TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Таблиця поточного стану
CREATE TABLE IF NOT EXISTS current_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    has_power BOOLEAN NOT NULL,
    last_change_time TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

-- Таблиця денної статистики
CREATE TABLE IF NOT EXISTS power_statistics (
    id SERIAL PRIMARY KEY,
    stat_date DATE NOT NULL UNIQUE,
    total_outages INTEGER DEFAULT 0,
    planned_outages INTEGER DEFAULT 0,
    emergency_outages INTEGER DEFAULT 0,
    total_outage_duration_seconds INTEGER DEFAULT 0,
    longest_outage_seconds INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Індекси для швидкого пошуку
CREATE INDEX IF NOT EXISTS idx_power_events_time ON power_events(event_time DESC);
CREATE INDEX IF NOT EXISTS idx_power_events_date ON power_events(DATE(event_time));
CREATE INDEX IF NOT EXISTS idx_statistics_date ON power_statistics(stat_date DESC);

-- Функція для оновлення статистики
CREATE OR REPLACE FUNCTION update_power_statistics()
RETURNS TRIGGER AS $$
DECLARE
    event_date DATE;
BEGIN
    event_date := DATE(NEW.event_time);
    
    -- Вставляємо або оновлюємо статистику за день
    INSERT INTO power_statistics (stat_date, total_outages, planned_outages, emergency_outages, total_outage_duration_seconds, longest_outage_seconds)
    VALUES (
        event_date,
        CASE WHEN NOT NEW.has_power THEN 1 ELSE 0 END,
        CASE WHEN NOT NEW.has_power AND NEW.is_planned THEN 1 ELSE 0 END,
        CASE WHEN NOT NEW.has_power AND NOT NEW.is_planned THEN 1 ELSE 0 END,
        CASE WHEN NOT NEW.has_power THEN NEW.duration_seconds ELSE 0 END,
        CASE WHEN NOT NEW.has_power THEN NEW.duration_seconds ELSE 0 END
    )
    ON CONFLICT (stat_date) DO UPDATE SET
        total_outages = power_statistics.total_outages + CASE WHEN NOT NEW.has_power THEN 1 ELSE 0 END,
        planned_outages = power_statistics.planned_outages + CASE WHEN NOT NEW.has_power AND NEW.is_planned THEN 1 ELSE 0 END,
        emergency_outages = power_statistics.emergency_outages + CASE WHEN NOT NEW.has_power AND NOT NEW.is_planned THEN 1 ELSE 0 END,
        total_outage_duration_seconds = power_statistics.total_outage_duration_seconds + CASE WHEN NOT NEW.has_power THEN NEW.duration_seconds ELSE 0 END,
        longest_outage_seconds = GREATEST(power_statistics.longest_outage_seconds, CASE WHEN NOT NEW.has_power THEN NEW.duration_seconds ELSE 0 END),
        updated_at = NOW();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Тригер для автоматичного оновлення статистики
DROP TRIGGER IF EXISTS trigger_update_statistics ON power_events;
CREATE TRIGGER trigger_update_statistics
    AFTER INSERT ON power_events
    FOR EACH ROW
    EXECUTE FUNCTION update_power_statistics();

-- Функція для оновлення updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Тригер для current_state
DROP TRIGGER IF EXISTS trigger_current_state_updated_at ON current_state;
CREATE TRIGGER trigger_current_state_updated_at
    BEFORE UPDATE ON current_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Вставляємо початковий стан (якщо таблиця порожня)
INSERT INTO current_state (id, has_power, last_change_time)
VALUES (1, TRUE, NOW())
ON CONFLICT (id) DO NOTHING;

-- Створюємо view для зручного перегляду статистики
CREATE OR REPLACE VIEW v_daily_statistics AS
SELECT 
    stat_date,
    total_outages,
    planned_outages,
    emergency_outages,
    CONCAT(
        FLOOR(total_outage_duration_seconds / 3600), ' год. ',
        FLOOR((total_outage_duration_seconds % 3600) / 60), ' хв.'
    ) AS total_outage_duration,
    CONCAT(
        FLOOR(longest_outage_seconds / 3600), ' год. ',
        FLOOR((longest_outage_seconds % 3600) / 60), ' хв.'
    ) AS longest_outage
FROM power_statistics
ORDER BY stat_date DESC;

-- Створюємо view для останніх подій
CREATE OR REPLACE VIEW v_recent_events AS
SELECT 
    event_time AT TIME ZONE 'Europe/Kiev' as event_time_kyiv,
    CASE WHEN has_power THEN '🟢 Світло є' ELSE '🔴 Світла немає' END as status,
    CONCAT(
        FLOOR(duration_seconds / 3600), ' год. ',
        FLOOR((duration_seconds % 3600) / 60), ' хв.'
    ) AS duration,
    CASE WHEN is_planned THEN '📋 Планове' ELSE '⚠️ Аварійне' END as outage_type
FROM power_events
ORDER BY event_time DESC
LIMIT 10;
