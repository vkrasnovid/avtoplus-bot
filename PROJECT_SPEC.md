# АвтоПлюс — Telegram бот для записи на автосервис

## Обзор
Telegram бот для автосервиса "АвтоПлюс". Клиенты записываются на обслуживание, админ управляет записями. Всё через один бот.

## Роли
- **Клиент** — любой пользователь Telegram
- **Админ** — один человек (владелец автосервиса), определяется по Telegram ID

## Функционал клиента

### Запись на обслуживание:
1. Клиент нажимает "Записаться"
2. Вводит марку и модель авто (текстом)
3. Выбирает услугу из списка (inline кнопки)
4. Выбирает дату из доступных (ближайшие 14 дней)
5. Выбирает время из свободных слотов
6. Подтверждает запись
7. Получает подтверждение с деталями

### Услуги (фиксированный список):
- Замена масла
- Диагностика двигателя
- Шиномонтаж
- Замена тормозных колодок
- Развал-схождение
- ТО (техобслуживание)
- Ремонт подвески
- Диагностика ходовой

### Слоты:
- Рабочие часы: 9:00 — 18:00
- Интервал: каждый час (9:00, 10:00, ..., 17:00) = 9 слотов в день
- Максимум записей на слот: 4 (количество постов/подъёмников)
- Выходные: суббота, воскресенье (не показываются)

### Мои записи:
- Список всех записей клиента (предстоящие + история)
- Статусы: Ожидает, Подтверждена, Завершена, Отменена
- Кнопка "Отменить" для предстоящих записей

### Напоминания:
- За 24 часа до визита — автоматическое сообщение клиенту
- "Напоминаем: завтра в 14:00 у вас запись на Замену масла. Ждём вас!"

## Функционал админа

### Уведомления:
- При новой записи: "Новая запись! Иван (@ivan) — Toyota Camry — Замена масла — 22.03 в 14:00"
- При отмене: "Запись отменена: Иван — 22.03 в 14:00"

### Управление записями:
- Список записей на сегодня / завтра / выбранную дату
- Подтверждение записи
- Завершение записи
- Отмена записи с причиной

### Статистика:
- Записей за сегодня / неделю / месяц
- Самые популярные услуги
- Процент отмен

## Технический стек
- **Язык:** Python 3.11+
- **Фреймворк бота:** aiogram 3.x
- **База данных:** SQLite (aiosqlite) — для простоты, без внешнего сервера
- **Планировщик:** APScheduler — для напоминаний
- **Деплой:** Docker

## Структура проекта
```
avtoplus-bot/
  bot/
    __init__.py
    main.py           # Entry point
    config.py          # Settings, bot token, admin ID
    database/
      __init__.py
      models.py        # SQLAlchemy/dataclass models
      db.py            # DB connection, init, migrations
    handlers/
      __init__.py
      start.py         # /start, главное меню
      booking.py       # Процесс записи
      my_bookings.py   # Мои записи
      admin.py         # Админ панель
    keyboards/
      __init__.py
      client.py        # Клавиатуры клиента
      admin.py         # Клавиатуры админа
    services/
      __init__.py
      booking_service.py  # Бизнес-логика записей
      reminder_service.py # Напоминания
      stats_service.py    # Статистика
    utils/
      __init__.py
      helpers.py
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  README.md
```

## Модели данных

### users
- id: INTEGER PK
- telegram_id: INTEGER UNIQUE
- username: TEXT (nullable)
- first_name: TEXT
- phone: TEXT (nullable)
- created_at: DATETIME

### bookings
- id: INTEGER PK
- user_id: INTEGER FK → users
- car_brand: TEXT
- car_model: TEXT
- service: TEXT
- booking_date: DATE
- booking_time: TIME
- status: TEXT (pending/confirmed/completed/cancelled)
- created_at: DATETIME
- cancelled_at: DATETIME (nullable)
- cancel_reason: TEXT (nullable)

### Нет таблицы services — список захардкожен в коде (фиксированный)

## Конфигурация (.env)
```
BOT_TOKEN=xxx
ADMIN_TELEGRAM_ID=xxx
TIMEZONE=Europe/Moscow
WORKING_HOURS_START=9
WORKING_HOURS_END=18
MAX_SLOTS_PER_HOUR=4
BOOKING_DAYS_AHEAD=14
```

## Нефункциональные требования
- Бот отвечает < 1 сек
- Корректная обработка concurrent записей (не овербукить слот)
- Graceful shutdown
- Логирование всех действий
- Все тексты на русском
