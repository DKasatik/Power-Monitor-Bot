FROM python:3.11-slim

# Встановлюємо часовий пояс
ENV TZ=Europe/Kiev
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y \
    gcc \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо Python залежності
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо всі файли проекту
COPY yasno_parser.py .
COPY tuya_monitor.py .
COPY telegram_bot.py .
COPY database.py .
COPY config.py .

# Запускаємо бота
CMD ["python", "-u", "telegram_bot.py"]
