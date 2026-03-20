# АвтоПлюс — Telegram-бот для записи на автосервис

- **Branch:** `feature/telegram-booking-bot`
- **Created:** 2026-03-20
- **Description:** Полная реализация Telegram-бота для автосервиса АвтоПлюс: запись клиентов, управление записями (админ), напоминания, статистика.

## Settings

- **Testing:** no
- **Logging:** verbose (DEBUG level, детальные логи на всех этапах)
- **Docs:** no (warn-only, без обязательного чекпоинта)

## Roadmap Linkage

- **Milestone:** none
- **Rationale:** Skipped by user

---

## Phase 1: Project Scaffolding & Config

### Task 1 — [x] Инициализировать структуру проекта

**Deliverable:** Все директории и пустые `__init__.py` созданы, `requirements.txt` и `.env.example` заполнены.

**Files to create:**
- `bot/__init__.py`
- `bot/database/__init__.py`
- `bot/handlers/__init__.py`
- `bot/keyboards/__init__.py`
- `bot/services/__init__.py`
- `bot/utils/__init__.py`
- `requirements.txt`
- `.env.example`

**What to do:**
- Создать все директории и пустые `__init__.py`
- В `requirements.txt` добавить: `aiogram==3.x`, `aiosqlite`, `apscheduler`, `python-dotenv`
- В `.env.example` добавить все переменные из спецификации (`BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `TIMEZONE`, `WORKING_HOURS_START`, `WORKING_HOURS_END`, `MAX_SLOTS_PER_HOUR`, `BOOKING_DAYS_AHEAD`)

**Logging:** нет (чистая инициализация структуры)

---

### Task 2 — [x] Реализовать `bot/config.py`

**Deliverable:** Модуль конфигурации, читающий `.env` через `python-dotenv`, с валидацией обязательных полей.

**Files to create/modify:**
- `bot/config.py`

**What to do:**
- Загружать переменные окружения через `dotenv`
- Экспортировать константы: `BOT_TOKEN`, `ADMIN_TELEGRAM_ID` (int), `TIMEZONE`, `WORKING_HOURS_START` (int), `WORKING_HOURS_END` (int), `MAX_SLOTS_PER_HOUR` (int), `BOOKING_DAYS_AHEAD` (int)
- Список `SERVICES` захардкодить здесь (8 услуг из спека)
- При отсутствии обязательного поля — выбросить `ValueError` с понятным сообщением

**Logging:**
- `DEBUG`: все загруженные настройки (кроме токена) при старте

---

## Phase 2: Database Layer

### Task 3 — [x] Реализовать `bot/database/models.py`

**Deliverable:** Датаклассы/named tuples для `User` и `Booking` — строгая типизация строк БД.

**Files to create/modify:**
- `bot/database/models.py`

**What to do:**
- Определить датакласс `User` (поля: `id`, `telegram_id`, `username`, `first_name`, `phone`, `created_at`)
- Определить датакласс `Booking` (поля: `id`, `user_id`, `car_brand`, `car_model`, `service`, `booking_date`, `booking_time`, `status`, `created_at`, `cancelled_at`, `cancel_reason`, `reminder_sent: bool = False`)
- Константы статусов: `PENDING = "pending"`, `CONFIRMED = "confirmed"`, `COMPLETED = "completed"`, `CANCELLED = "cancelled"`
- `reminder_sent` — флаг, что напоминание уже отправлено (хранится в БД для персистентности между рестартами)

**Logging:** нет (чистые модели)

---

### Task 4 — [x] Реализовать `bot/database/db.py`

**Deliverable:** Инициализация БД, создание таблиц, CRUD-операции для `users` и `bookings`.

**Files to create/modify:**
- `bot/database/db.py`

**What to do:**
- Использовать `aiosqlite` с пулом соединений (или shared connection)
- `init_db()` — создаёт таблицы `users` и `bookings` если не существуют (schema из спека)
- `get_or_create_user(telegram_id, username, first_name)` → `User`
- `create_booking(user_id, car_brand, car_model, service, booking_date, booking_time)` → `Booking`
- `get_user_bookings(user_id)` → `list[Booking]`
- `get_bookings_by_date(date)` → `list[Booking]`
- `get_slot_count(booking_date, booking_time)` → `int` (для проверки доступности)
- `update_booking_status(booking_id, status, cancel_reason=None)` → `bool`
- `get_booking_by_id(booking_id)` → `Booking | None`
- `get_pending_reminders(target_date: date)` → `list[Booking]` — записи на `target_date` со статусом `pending`/`confirmed` и `reminder_sent = False`
- `mark_reminder_sent(booking_id)` → `None` — выставить `reminder_sent = True`
- `get_stats_by_period(start_date: date, end_date: date)` → `dict` — агрегат `{status: count}` за период (используется в stats_service)
- `get_popular_services_from_db(limit: int = 5)` → `list[tuple[str, int]]` — топ услуг по числу записей (GROUP BY service)
- `get_cancellation_rate_from_db()` → `float` — `cancelled / total * 100`
- Использовать `PRAGMA journal_mode=WAL` для concurrent writes
- Schema `bookings` включает колонку `reminder_sent INTEGER NOT NULL DEFAULT 0`

**Logging:**
- `DEBUG`: каждый SQL-запрос с параметрами
- `INFO`: успешное создание записи (`booking_id=N`)
- `WARNING`: попытка создания записи в занятом слоте (до проверки в сервисе)
- `ERROR`: исключения БД с полным трейсбеком

---

## Phase 3: Business Logic Services

### Task 5 — [x] Реализовать `bot/services/booking_service.py`

**Deliverable:** Бизнес-логика: доступные даты/слоты, создание/отмена записей с проверкой concurrent access.

**Files to create/modify:**
- `bot/services/booking_service.py`

**What to do:**
- `get_available_dates()` → `list[date]` — ближайшие N рабочих дней (не считая выходные), N = `BOOKING_DAYS_AHEAD`
- `get_available_slots(booking_date)` → `list[time]` — слоты с `WORKING_HOURS_START` до `WORKING_HOURS_END-1`, отфильтровав заполненные (≥ `MAX_SLOTS_PER_HOUR`)
- `create_booking(user_id, car_brand, car_model, service, booking_date, booking_time)` → `Booking | None` — с проверкой слота и atomic insert (SELECT + INSERT в одной транзакции)
- `cancel_booking(booking_id, user_id=None)` → `bool` — проверить, что запись принадлежит user_id (если передан) и статус позволяет отмену
- `get_user_bookings(user_id)` → `list[Booking]`

**Logging:**
- `DEBUG`: входные параметры каждого публичного метода
- `INFO`: успешное создание/отмена записи с деталями (user_id, service, date, time)
- `WARNING`: слот занят при попытке записи; невалидный статус при отмене
- `ERROR`: исключения с трейсбеком

---

### Task 6 — [x] Реализовать `bot/services/stats_service.py`

**Deliverable:** Агрегированная статистика для админа.

**Files to create/modify:**
- `bot/services/stats_service.py`

**What to do:**
- `get_stats_today()` → `dict` — вызывает `db.get_stats_by_period(today, today)`
- `get_stats_week()` → `dict` — вызывает `db.get_stats_by_period(week_start, today)`
- `get_stats_month()` → `dict` — вызывает `db.get_stats_by_period(month_start, today)`
- `get_popular_services()` → `list[tuple[str, int]]` — делегирует в `db.get_popular_services_from_db()`
- `get_cancellation_rate()` → `float` — делегирует в `db.get_cancellation_rate_from_db()`
- Форматирует результаты в читаемый текст для отправки в Telegram

**Logging:**
- `DEBUG`: запрошенный период и результат каждой функции

---

### Task 7 — [x] Реализовать `bot/services/reminder_service.py`

**Deliverable:** APScheduler-задача, отправляющая напоминания за 24ч до записи.

**Files to create/modify:**
- `bot/services/reminder_service.py`

**What to do:**
- Использовать `AsyncIOScheduler` из `apscheduler`
- Задача запускается каждый час (cron): вызывает `db.get_pending_reminders(tomorrow)` — записи на завтра с `reminder_sent = False`
- Отправляет сообщение клиенту через `bot.send_message`
- Текст: `"Напоминаем: завтра в {time} у вас запись на {service}. Ждём вас!"`
- После успешной отправки — вызывает `db.mark_reminder_sent(booking_id)` (персистентный флаг в БД, не сбрасывается при рестарте)
- `tomorrow` = `date.today() + timedelta(days=1)` с учётом `TIMEZONE`

**Logging:**
- `DEBUG`: проверка напоминаний запущена, найдено N записей
- `INFO`: напоминание отправлено (booking_id, user telegram_id)
- `WARNING`: не удалось отправить (пользователь заблокировал бота)
- `ERROR`: исключения планировщика

---

> **Commit checkpoint 1** (после Task 7):
> ```
> feat: add database layer, services, and reminder scheduler
> ```

---

## Phase 4: Keyboards

### Task 8 — [x] Реализовать `bot/keyboards/client.py`

**Deliverable:** Все inline и reply клавиатуры для клиента.

**Files to create/modify:**
- `bot/keyboards/client.py`

**What to do:**
- `main_menu_kb()` → `ReplyKeyboardMarkup` — кнопки "Записаться", "Мои записи"
- `services_kb()` → `InlineKeyboardMarkup` — инлайн-кнопки для каждой услуги (callback: `service:{name}`)
- `dates_kb(dates: list[date])` → `InlineKeyboardMarkup` — кнопки с датами (формат: `ДД.ММ`, callback: `date:{iso}`)
- `slots_kb(slots: list[time])` → `InlineKeyboardMarkup` — кнопки со временем (callback: `slot:{HH:MM}`)
- `confirm_kb()` → `InlineKeyboardMarkup` — кнопки "Подтвердить" и "Отмена"
- `booking_actions_kb(booking_id)` → `InlineKeyboardMarkup` — кнопка "Отменить запись" (callback: `cancel_booking:{id}`)

**Logging:**
- `DEBUG`: какая клавиатура создаётся и с какими параметрами

---

### Task 9 — [x] Реализовать `bot/keyboards/admin.py`

**Deliverable:** Все клавиатуры для Admin Panel.

**Files to create/modify:**
- `bot/keyboards/admin.py`

**What to do:**
- `admin_main_kb()` → `ReplyKeyboardMarkup` — кнопки "Записи сегодня", "Записи завтра", "Выбрать дату", "Статистика"
- `admin_date_picker_kb(dates)` → `InlineKeyboardMarkup` — выбор даты (callback: `admin_date:{iso}`)
- `booking_manage_kb(booking_id)` → `InlineKeyboardMarkup` — кнопки "Подтвердить", "Завершить", "Отменить" (callback: `admin_confirm:{id}`, `admin_complete:{id}`, `admin_cancel:{id}`)

**Logging:**
- `DEBUG`: какая клавиатура создаётся

---

## Phase 5: Handlers

### Task 10 — [x] Реализовать `bot/handlers/start.py`

**Deliverable:** Обработчик `/start` и главного меню.

**Files to create/modify:**
- `bot/handlers/start.py`

**What to do:**
- `cmd_start(message, db)` — регистрирует/обновляет пользователя, отправляет приветствие с главным меню
- Текст приветствия: `"Добро пожаловать в АвтоПлюс! Выберите действие:"`
- Если пользователь — админ (`message.from_user.id == ADMIN_TELEGRAM_ID`), показывать `admin_main_kb()` вместо `main_menu_kb()`
- Зарегистрировать handler в router

**Logging:**
- `DEBUG`: `user_id={telegram_id}` вошёл
- `INFO`: новый пользователь зарегистрирован

---

### Task 11 — [x] Реализовать `bot/handlers/booking.py` (FSM)

**Deliverable:** Полный FSM-флоу записи на обслуживание (5 шагов).

**Files to create/modify:**
- `bot/handlers/booking.py`

**What to do:**
- Определить `BookingStates(StatesGroup)`: `waiting_car`, `waiting_service`, `waiting_date`, `waiting_slot`, `waiting_confirm`
- Шаг 1: Нажатие "Записаться" → запрос марки/модели авто одним сообщением (`waiting_car`)
  - Сообщение пользователю: `"Введите марку и модель автомобиля (например: Toyota Camry, BMW 3 Series)"`
- Шаг 2 (Variant A — единое поле): Пользователь вводит строку → парсим:
  - `parts = text.strip().split(None, 1)` — первое слово = `car_brand`, остаток = `car_model`
  - Валидация: минимум 2 слова. Если одно слово — отправить `"Пожалуйста, укажите и марку, и модель. Например: Toyota Camry"` и остаться в `waiting_car`
  - Сохранить `car_brand` и `car_model` в FSM data → показать `services_kb()` → перейти в `waiting_service`
- Шаг 3: Выбор услуги → показ `dates_kb()` (`waiting_date`)
- Шаг 4: Выбор даты → показ `slots_kb()` (`waiting_slot`)
- Шаг 5: Выбор слота → показ `confirm_kb()` с деталями (`waiting_confirm`)
- Подтверждение: вызов `booking_service.create_booking()`, отправка подтверждения, уведомление админа
- Отмена на любом шаге: команда `/cancel` (зарегистрировать отдельным хендлером в этом же роутере) или кнопка "Отмена"
- Текст подтверждения клиенту: `"Запись подтверждена!\n{детали}"`
- Текст уведомления админу: `"Новая запись! {first_name} (@{username}) — {car_brand} {car_model} — {service} — {date} в {time}"`

**Logging:**
- `DEBUG`: каждый переход состояний (from → to, user_id)
- `INFO`: запись создана (booking_id, user_id, service, date, time)
- `WARNING`: слот занят — сообщить пользователю и вернуться к выбору слота
- `ERROR`: исключения с трейсбеком

---

### Task 12 — [x] Реализовать `bot/handlers/my_bookings.py`

**Deliverable:** Просмотр и отмена своих записей клиентом.

**Files to create/modify:**
- `bot/handlers/my_bookings.py`

**What to do:**
- По нажатию "Мои записи" — вывести список записей пользователя (все, включая историю)
- Для каждой записи: дата, время, услуга, статус (на русском), кнопка "Отменить" для предстоящих (`pending`/`confirmed`)
- Обработчик `cancel_booking_callback` — отменить запись, уведомить пользователя и админа
- Текст уведомления админу при отмене: `"Запись отменена: {first_name} — {date} в {time}"`
- Если записей нет — `"У вас пока нет записей"`

**Logging:**
- `DEBUG`: user_id запросил список записей, найдено N
- `INFO`: запись N отменена пользователем user_id

---

### Task 13 — [x] Реализовать `bot/handlers/admin.py`

**Deliverable:** Полная Admin Panel: просмотр записей, управление статусами, статистика.

**Files to create/modify:**
- `bot/handlers/admin.py`

**What to do:**
- Функция `is_admin(telegram_id: int) -> bool` реализована в `bot/utils/helpers.py` (проверка `telegram_id == ADMIN_TELEGRAM_ID`); импортировать из там
- Все хендлеры защищены: в начале каждого admin-хендлера — `if not is_admin(message.from_user.id): return`
- "Записи сегодня" / "Записи завтра" — список записей за день с кнопками управления
- "Выбрать дату" — показать `admin_date_picker_kb()`
- "Статистика" — отправить сообщение с данными от `stats_service`
- Callbacks `admin_confirm:{id}`, `admin_complete:{id}`, `admin_cancel:{id}` — изменить статус записи
- При `admin_cancel` — запросить причину (FSM: `AdminStates.waiting_cancel_reason`)
- После каждого действия — уведомить клиента об изменении статуса

**Logging:**
- `DEBUG`: admin action = {action}, booking_id = {id}
- `INFO`: статус записи изменён (booking_id, old_status → new_status)
- `WARNING`: попытка не-админа вызвать admin handler (user_id)

---

> **Commit checkpoint 2** (после Task 13):
> ```
> feat: add all bot handlers (start, booking FSM, my_bookings, admin)
> ```

---

## Phase 6: Infrastructure

### Task 14 — [x] Реализовать `bot/main.py` и вспомогательные модули

**Deliverable:** Entry point: инициализация бота, диспетчера, роутеров, планировщика, graceful shutdown.

**Files to create/modify:**
- `bot/main.py`
- `bot/utils/helpers.py`

**What to do:**
- `main.py`:
  - Настроить `logging` (уровень `DEBUG`, формат с timestamp, module, level)
  - Инициализировать `Bot(token=BOT_TOKEN)` и `Dispatcher()`
  - Подключить все роутеры (start, booking, my_bookings, admin)
  - Вызвать `init_db()` при старте
  - Запустить `AsyncIOScheduler` с задачей напоминаний
  - `dp.start_polling(bot, allowed_updates=...)` с graceful shutdown (SIGTERM/SIGINT)
- `helpers.py`:
  - `format_date(date)` → `str` (формат `"ДД.ММ.ГГГГ"`)
  - `format_time(time)` → `str` (формат `"ЧЧ:ММ"`)
  - `status_to_russian(status)` → `str`
  - `is_admin(telegram_id: int) -> bool` — сравнение с `ADMIN_TELEGRAM_ID` (используется в admin-хендлере)

**Logging:**
- `INFO`: бот запущен, версия aiogram, timezone
- `INFO`: shutdown получен, graceful stop
- `DEBUG`: каждое входящее обновление (update_id, type)

---

### Task 15 — [x] Docker-конфигурация

**Deliverable:** `Dockerfile` и `docker-compose.yml` для dev и prod окружений.

**Files to create/modify:**
- `Dockerfile`
- `docker-compose.yml`

**What to do:**
- `Dockerfile`: multi-stage, base = `python:3.11-slim`, COPY requirements.txt → pip install → COPY bot/ → `CMD ["python", "-m", "bot.main"]`
- `docker-compose.yml`: сервис `bot`, монтировать `./data:/app/data` для SQLite, передавать `.env` через `env_file`
- Volume для БД: `./data/avtoplus.db` — чтобы данные сохранялись при рестарте

**Logging:** нет

---

> **Commit checkpoint 3** (после Task 15 — финальный):
> ```
> feat: add docker configuration and finalize bot implementation
> ```

---

## Commit Plan

| Checkpoint | After Task | Message |
|---|---|---|
| 1 | Task 7 | `feat: add database layer, services, and reminder scheduler` |
| 2 | Task 13 | `feat: add all bot handlers (start, booking FSM, my_bookings, admin)` |
| 3 | Task 15 | `feat: add docker configuration and finalize bot implementation` |

---

## Summary

**15 tasks** across 6 phases:
1. Project Scaffolding (Tasks 1-2)
2. Database Layer (Tasks 3-4)
3. Business Logic Services (Tasks 5-7)
4. Keyboards (Tasks 8-9)
5. Handlers (Tasks 10-13)
6. Infrastructure (Tasks 14-15)
