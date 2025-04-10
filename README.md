# Telegram Ghibli Style Bot

Этот телеграм бот преобразует загруженные пользователями фотографии в стиль анимационной студии Ghibli, используя API OpenAI.

## Функциональность

1. Пользователь отправляет фотографию в чат с ботом
2. Бот анализирует изображение с помощью GPT-4o
3. На основе анализа генерирует новое изображение в стиле Ghibli с помощью DALL-E 3
4. Отправляет результат пользователю

## Настройка переменных окружения

Бот использует следующие переменные окружения:

- `TELEGRAM_TOKEN` - токен вашего Telegram бота (получить у @BotFather)
- `OPENAI_API_KEY` - ключ API OpenAI для доступа к DALL-E и GPT
- `BOT_USERNAME` - имя вашего бота (опционально)

Для локальной разработки создайте файл `.env` в корне проекта со следующим содержимым:

```
TELEGRAM_TOKEN=ваш_телеграм_токен
OPENAI_API_KEY=ваш_ключ_openai
BOT_USERNAME=имя_вашего_бота
```

## Установка и локальный запуск

1. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```

2. Создайте файл `.env` с вашими API ключами (см. выше)

3. Запустите бота:
   ```
   python bot.py
   ```

## Деплой на Railway

1. Создайте аккаунт на [Railway.app](https://railway.app)

2. Создайте новый проект и выберите деплой из GitHub репозитория

3. Настройте переменные окружения в разделе "Variables":
   - `TELEGRAM_TOKEN`
   - `OPENAI_API_KEY`
   - `BOT_USERNAME` (опционально)

4. В разделе "Settings" укажите команду запуска:
   ```
   python bot.py
   ```

5. Railway автоматически задеплоит ваш бот и будет обновлять его при каждом пуше в репозиторий
   ```

## Технические детали

- Используется Python-Telegram-Bot для работы с Telegram API
- OpenAI API для обработки изображений (GPT-4o + DALL-E 3)
- Процесс обработки включает:
  - Анализ изображения через Vision API
  - Генерацию нового изображения через DALL-E 3
  
## Команды бота

- `/start` - Приветственное сообщение и инструкции
- `/help` - Подробная справка по использованию бота
