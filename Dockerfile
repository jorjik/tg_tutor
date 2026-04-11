FROM python:3.13-slim

WORKDIR /app

# Устанавливаем зависимости отдельным слоем для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# По умолчанию запускаем бот; в docker-compose.yml команда переопределяется для веб-сервиса
CMD ["python", "-m", "app.bot.main"]
