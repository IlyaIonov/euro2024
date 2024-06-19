FROM python:3.10

# Установка рабочей директории
WORKDIR /app/src

# Копирование requirements.txt и установка зависимостей
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Клонирование репозитория
RUN git clone https://github.com/IlyaIonov/euro2024.git

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt


# Копируем остальные файлы приложения в рабочую директорию
COPY . .

# Устанавливаем переменную окружения для токена бота
ENV TELEGRAM_BOT_TOKEN="7474632587:AAFBK6qWIOYE5zm29Wmw1WifhtuwF-LoG-Y"

# Запускаем приложение
CMD ["python", "bot.py"]