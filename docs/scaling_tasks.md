# План масштабирования tg_tutor

Задачи сгруппированы по этапам роста. Каждая задача — самостоятельная единица работы с целью, объёмом и критерием готовности.

---

## Этап 0. Быстрые победы (до ~500 DAU)

### Задача 0.1. Per-user rate limit / антифлуд middleware
**Цель:** один пользователь не может держать больше одного активного запроса к OpenAI и не может отправлять чаще N сообщений в минуту.

**Объём:**
- Новый `app/bot/middlewares/throttle.py` — `BaseMiddleware` на уровне message router.
- In-memory структура: `dict[user_id, asyncio.Lock]` + `dict[user_id, deque[timestamp]]` (скользящее окно).
- Лимит по умолчанию: 1 параллельный запрос + 10 сообщений/минуту (в `Settings`).
- При превышении — мгновенный ответ «Подожди, предыдущий запрос ещё обрабатывается» / «Слишком часто, попробуй через N сек», без вызова OpenAI.
- Подключить в `app/bot/main.py` через `dp.message.middleware(...)`.

**Готово когда:**
- Быстрые повторные нажатия не создают параллельных `responses.create`.
- Тест `tests/bot/test_throttle.py` проверяет блокировку 2-го запроса и освобождение после завершения.

---

### Задача 0.2. Таймаут и retry для OpenAI
**Цель:** зависший вызов OpenAI не блокирует корутину бесконечно; сетевые ошибки переживаются без падения хендлера.

**Объём:**
- В `app/services/openai_client.py` — передать `timeout=60.0` и `max_retries=2` в `AsyncOpenAI`.
- В `chat_service.answer_user_message` обернуть вызов в `try/except` на `APITimeoutError`, `APIConnectionError`, `RateLimitError`.
- При таймауте/ошибке — пользователю понятный текст, в лог — WARNING, usage НЕ инкрементируется.

**Готово когда:**
- Симуляция таймаута (monkeypatch клиента) возвращает пользователю сообщение об ошибке и не роняет хендлер.

---

### Задача 0.3. Наблюдаемость: Sentry + метрики
**Цель:** видеть ошибки в проде и среднее/p95 время ответа OpenAI.

**Объём:**
- `sentry-sdk` в `requirements.txt`, инициализация в `app/bot/main.py` при наличии `SENTRY_DSN` в Settings.
- В `chat_service` — замерять время вокруг `responses.create` и логировать структурно (`logging.info("openai_latency", extra={...})`).
- (Опционально) `/admin/stats` добавляет среднее время ответа за 24ч из `chat_messages` либо in-memory счётчика.

**Готово когда:**
- В Sentry видны exceptions из бота; в логах — latency каждого вызова OpenAI.

---

### Задача 0.4. Индексы и ревизия запросов к БД
**Цель:** убедиться, что подгрузка истории и админ-выборки не деградируют с ростом `chat_messages`.

**Объём:**
- Проверить наличие индекса `chat_messages(user_id, created_at DESC, id DESC)`. Если нет — новая Alembic-ревизия.
- Пройтись по `admin_service` — `EXPLAIN` тяжёлых выборок, при необходимости добавить индексы на `subscriptions.user_id`, `payments.user_id`.

**Готово когда:**
- `EXPLAIN ANALYZE` на выборке истории — Index Scan, не Seq Scan.

---

## Этап 1. Webhook + Redis + очередь (500–5 000 DAU)

### Задача 1.1. Telegram webhook через FastAPI
**Цель:** уйти от polling, получить горизонтальную масштабируемость приёма апдейтов.

**Объём:**
- `app/web/app.py` (FastAPI) — уже запланирован, добавить туда endpoint `POST /tg/webhook/{secret}`.
- Использовать `aiogram.webhook.SimpleRequestHandler` или руками прокинуть `dispatcher.feed_update`.
- Скрипт/команда `app/scripts/set_webhook.py` для `bot.set_webhook(url, secret_token=...)`.
- В `docker-compose.yml` — пробросить порт `web`, Nginx/Traefik с TLS (Let's Encrypt) как reverse-proxy.
- Убрать `polling`-команду из сервиса `bot` (или оставить как dev-профиль через `COMPOSE_PROFILES`).

**Готово когда:**
- Telegram успешно доставляет апдейты на HTTPS endpoint, бот отвечает.
- `getWebhookInfo` показывает нулевую очередь.

---

### Задача 1.2. Redis + вынос кэша истории
**Цель:** заменить in-memory `_msg_cache` на Redis, чтобы кэш переживал рестарт и шарился между воркерами.

**Объём:**
- Сервис `redis` в `docker-compose.yml`, настройка в `Settings`.
- `app/services/cache.py` — тонкая обёртка над `redis.asyncio.Redis` (get/set JSON с TTL).
- В `chat_service._load_recent_messages` / `_cache_set_msgs` — переключить на Redis. Ключ `chat:history:{user_id}`, TTL 10 минут.
- Rate-limit из задачи 0.1 также мигрировать в Redis (`INCR` + `EXPIRE`) — для работы в N инстансах.

**Готово когда:**
- Рестарт бота не «теряет» контекст активных диалогов.
- Rate-limit работает одинаково между двумя запущенными репликами.

---

### Задача 1.3. Фоновая очередь для вызовов OpenAI
**Цель:** HTTP-ответ вебхука возвращается мгновенно; длинный GPT-вызов уходит в воркер.

**Объём:**
- Подключить `arq` (либо `dramatiq` / `taskiq`) поверх Redis.
- Новая таска `process_user_message(update_payload)`:
  1. send_chat_action "typing"
  2. вызов `answer_user_message`
  3. `bot.send_message` с ответом
- В вебхук-хендлере: быстрый ack (200 OK) + enqueue.
- Отдельный сервис `worker` в `docker-compose.yml`.
- Idempotency по `update_id` через Redis `SETNX` с TTL (защита от повторной доставки Telegram).

**Готово когда:**
- Вебхук отвечает Telegram за <200 мс независимо от времени OpenAI.
- Падение воркера не теряет задачу (arq повторяет).

---

### Задача 1.4. PgBouncer и пул соединений
**Цель:** выдержать десятки воркеров без исчерпания `max_connections` Postgres.

**Объём:**
- Сервис `pgbouncer` в docker-compose (transaction pooling).
- `DATABASE_URL` воркеров и web указывает на PgBouncer.
- Проверить совместимость SQLAlchemy async + transaction pooling (отключить prepared statements: `connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}`).

**Готово когда:**
- При 20 параллельных воркерах нет ошибок `too many connections`.

---

### Задача 1.5. Токен-aware усечение контекста
**Цель:** стоимость и latency запроса не растут линейно с длиной диалога.

**Объём:**
- Считать токены через `tiktoken` для выбранной модели.
- В `_build_openai_messages` — обрезать историю так, чтобы `summary + history + user_text` укладывалось в бюджет (например 4 000 токенов).
- Вытесненные сообщения идут на суммаризацию в `user.conversation_summary` (отдельный дешёвый вызов, можно gpt-4o-mini).

**Готово когда:**
- Длинные диалоги не превышают заданный токен-бюджет, summary автоматически обновляется.

---

## Этап 2. Масштаб (5 000–50 000 DAU)

### Задача 2.1. Несколько реплик web и worker
**Цель:** горизонтальное масштабирование приёма и обработки.

**Объём:**
- `docker-compose` → Docker Swarm / k8s манифесты (или просто `deploy.replicas` + внешний балансировщик).
- Nginx/Traefik как L7-балансировщик перед `web`.
- Health-check endpoint `/healthz` в FastAPI.
- Graceful shutdown воркеров (arq умеет).

**Готово когда:**
- Нагрузочный тест (locust, 100 RPS) проходит без роста p95 выше 2× baseline.

---

### Задача 2.2. Read replica для админки
**Цель:** тяжёлые админ-выборки не влияют на основной трафик бота.

**Объём:**
- Настроить streaming replication Postgres (или managed реплика).
- В `app/db/session.py` — второй engine для read-only сессий.
- `admin_service` использует read-only engine.

**Готово когда:**
- Админ-статистика читается с реплики, основная БД свободна.

---

### Задача 2.3. Партиционирование `chat_messages`
**Цель:** таблица с десятками миллионов строк не деградирует.

**Объём:**
- Миграция: `chat_messages` → partitioned by range на `created_at` (по месяцам).
- Крон-задача создания будущих партиций + отрезания старых (архив в S3 / `chat_messages_archive`).

**Готово когда:**
- Размер горячей партиции <5M строк, запросы укладываются в <20 мс.

---

### Задача 2.4. Биллинг usage и бюджеты
**Цель:** видеть стоимость на пользователя, автоматически ограничивать злоупотребления.

**Объём:**
- В `UsageCounter` добавить `prompt_tokens`, `completion_tokens`, `cost_usd`.
- `answer_user_message` записывает реальные токены из response.
- Админ: топ-N пользователей по стоимости, алерт при превышении плана.

**Готово когда:**
- Видна стоимость на юзера за период, подписка учитывает токены/стоимость, а не только число сообщений.

---

## Этап 3. Зрелый продукт (50 000+ DAU)

### Задача 3.1. Managed инфраструктура
Переезд Postgres и Redis на managed (Neon/Supabase/Yandex Cloud), чтобы убрать операционку с команды.

### Задача 3.2. Мульти-ключ OpenAI + semantic cache
- Несколько API-ключей с round-robin и учётом tier-лимитов.
- Semantic cache (pgvector или Redis + embeddings) на частые вопросы — гасит 10–30% вызовов LLM.

### Задача 3.3. Шардирование бота
При упоре в Telegram-лимиты — разделить пользователей между несколькими ботами (`user_id % N`), единый бэкенд.

### Задача 3.4. Выделенный billing-service
Вынести подписки, ЮKassa-вебхуки, usage-агрегацию в отдельный сервис с собственной БД.

---

## Порядок выполнения

Рекомендуемая последовательность: **0.1 → 0.2 → 0.3 → 0.4 → 1.1 → 1.2 → 1.3 → 1.4 → 1.5**, далее по мере роста DAU.

Задачи 0.x можно делать параллельно, они независимы. Задачи 1.x имеют зависимость: 1.1 и 1.2 — предпосылки для 1.3.
