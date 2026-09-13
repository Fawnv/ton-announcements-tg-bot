# Используем легковесный образ Python
FROM python:3.11-slim

# Отключаем буферизацию вывода (логи сразу летят в docker logs) 
# и создание .pyc файлов
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Устанавливаем системные утилиты (если понадобятся для сборки)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаем директорию под базу данных SQLite, чтобы данные не терялись
RUN mkdir -p /app/data

# Запуск бота
CMD ["python", "main.py"]
