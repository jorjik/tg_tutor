# TG Tutor — Telegram-бот + ChatGPT + платная подписка

Python-бот на [aiogram 3](https://docs.aiogram.dev/) с доступом к ChatGPT через платную подписку.

**По умолчанию оплата идёт в Telegram Stars (XTR)** — нативный механизм Telegram, без внешнего платёжного провайдера и лишних интеграций. Дополнительно поддерживаются **Stripe** (sandbox «из коробки») и **ЮKassa** для оплаты обычными деньгами.

### Оптимизация под высокую нагрузку

Чтобы бот выдерживал большой поток пользователей без просадок на БД, в хот-пути добавлено in-memory TTL-кэширование:

- **Кэш активных подписок** ([subscription_service.py](app/services/subscription_service.py)) — middleware на каждом апдейте сначала читает подписку из памяти, в БД идёт только при промахе/истечении TTL или после изменения (активация/отмена вызывают `invalidate_subscription_cache`).
- **Кэш истории сообщений диалога** ([chat_service.py](app/services/chat_service.py)) — окно последних реплик для контекста ChatGPT держится в памяти и обновляется инкрементально, без повторных `SELECT` перед каждым ответом модели.
- **Синглтоны через `functools.lru_cache`** для `Settings`, async-движка SQLAlchemy и `AsyncOpenAI` — никаких пересозданий на каждом хэндлере.

Итог: типичный апдейт «сообщение → ответ» попадает в БД только для записи (usage-счётчики, новая реплика), а чтения по горячему пути обслуживаются из памяти процесса.

---

## Стек

| Компонент | Технология |
|-----------|-----------|
| Бот | aiogram 3.x |
| LLM | openai SDK (Responses API) |
| БД | PostgreSQL 16 + asyncpg + SQLAlchemy 2 async |
| Миграции | Alembic |
| Конфиг | pydantic-settings, `.env` |
| Платежи | Stripe (дефолт) / ЮKassa |
| HTTP-сервис | FastAPI + uvicorn |
| Деплой | VPS + Docker Compose |

---

## Быстрый старт (локально)

### 1. Клонировать и настроить окружение

```bash
cp .env.example .env
# Заполнить .env: BOT_TOKEN, OPENAI_API_KEY, STRIPE_SECRET_KEY
```

### 2. Запустить PostgreSQL

```bash
docker run -d --name pg \
  -e POSTGRES_DB=tg_tutor \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16-alpine
```

### 3. Установить зависимости и накатить миграции

```bash
pip install -r requirements.txt
alembic upgrade head
```

### 4. Запустить бота

```bash
python -m app.bot.main
```

### 5. Запустить веб-сервис (в другом терминале)

```bash
uvicorn app.web.app:app --reload
```

Веб-сервис доступен на `http://localhost:8000`:
- `GET /admin/` — веб-админка тарифов (Basic Auth: `admin` / `changeme`)
- `POST /webhooks/stripe` — вебхук Stripe
- `POST /webhooks/yookassa` — вебхук ЮKassa
- `GET /docs` — Swagger UI

### 6. Подключить Stripe (для тестирования оплаты)

В `.env` уже прописан `PAYMENT_PROVIDER=stripe`. Для получения вебхуков локально установите [Stripe CLI](https://stripe.com/docs/stripe-cli) и запустите в третьем терминале:

```bash
stripe login
stripe listen --forward-to localhost:8000/webhooks/stripe
```

Stripe CLI выведет `STRIPE_WEBHOOK_SECRET` — вставьте его в `.env` и перезапустите веб-сервис. После этого оплата в боте (`/subscribe`) будет работать полностью: бот создаёт Stripe Checkout Session → пользователь платит тестовой картой `4242 4242 4242 4242` → Stripe CLI проксирует вебхук → подписка активируется.

---

## Тестирование платежей (Stripe sandbox)

1. Создайте аккаунт на [dashboard.stripe.com](https://dashboard.stripe.com)
2. Скопируйте тестовые ключи (`sk_test_...`, `pk_test_...`) в `.env`
3. Для тестирования вебхуков локально установите [Stripe CLI](https://stripe.com/docs/stripe-cli):

```bash
stripe login
stripe listen --forward-to localhost:8000/webhooks/stripe
# Stripe CLI выдаст STRIPE_WEBHOOK_SECRET — скопируйте в .env
```

4. Создайте тариф через `/admin` в боте или через веб-админку
5. В боте: `/subscribe` → выберите тариф → оплатите тестовой картой `4242 4242 4242 4242`
6. После оплаты Stripe CLI проксирует вебхук → подписка активируется

---

## Тестирование платежей (ЮKassa)

```env
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=100500        # тестовый shop_id ЮKassa
YOOKASSA_SECRET_KEY=test_...   # тестовый ключ
```

Вебхуки в тестовом контуре ЮKassa доступны через [ngrok](https://ngrok.com) или [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
ngrok http 8000
# ngrok выдаст https://xxxx.ngrok.io
# Указать в настройках магазина ЮKassa: https://xxxx.ngrok.io/webhooks/yookassa
```

---

## Деплой на VPS (Docker Compose)

### 1. Подготовить сервер

```bash
# Ubuntu 22.04+
apt update && apt install -y docker.io docker-compose-plugin
```

### 2. Скопировать файлы и настроить .env

```bash
scp -r ./ user@your-vps:/opt/tg_tutor/
ssh user@your-vps
cd /opt/tg_tutor
cp .env.example .env
nano .env  # заполнить все переменные
```

### 3. Запустить

```bash
docker compose up -d --build
docker compose logs -f  # следить за логами
```

Сервисы:
- `migrate` — накатывает миграции перед стартом, затем останавливается
- `bot` — aiogram polling
- `web` — FastAPI на порту 8000
- `postgres` — PostgreSQL с volume для данных

### 4. HTTPS через Caddy (рекомендуется)

```bash
apt install -y caddy
```

`/etc/caddy/Caddyfile`:
```
your-domain.com {
    reverse_proxy localhost:8000
}
```

```bash
systemctl reload caddy
```

Теперь вебхуки доступны по `https://your-domain.com/webhooks/stripe`.

---

## Структура проекта

```
tg_tutor/
├── app/
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── admin/          # /admin: статистика, CRUD тарифов, пользователи
│   │   │   ├── chat.py         # текстовые сообщения → OpenAI
│   │   │   ├── common.py       # /start
│   │   │   └── user.py         # /status, /subscribe
│   │   ├── middleware/
│   │   │   └── subscription.py # проверка подписки и лимитов
│   │   └── main.py             # запуск polling
│   ├── db/
│   │   ├── models.py           # User, ChatMessage, Plan, Subscription, UsageCounter, Payment
│   │   └── session.py          # async engine
│   ├── services/
│   │   ├── admin_service.py    # бизнес-логика админки
│   │   ├── chat_service.py     # диалог с памятью + increment_usage
│   │   ├── openai_client.py    # AsyncOpenAI singleton
│   │   ├── subscription_service.py  # проверка подписки, лимитов, счётчики
│   │   └── payments/
│   │       ├── base.py         # абстракция PaymentProvider
│   │       ├── stripe_provider.py
│   │       └── yookassa_provider.py
│   ├── web/
│   │   ├── app.py              # FastAPI app
│   │   ├── auth.py             # HTTP Basic Auth
│   │   └── routes/
│   │       ├── admin.py        # веб-админка тарифов
│   │       └── webhooks.py     # POST /webhooks/stripe, /webhooks/yookassa
│   └── config.py               # pydantic-settings
├── alembic/                    # миграции БД
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Переменные окружения

| Переменная | Обязательная | Описание |
|-----------|:---:|---------|
| `BOT_TOKEN` | ✅ | Токен бота из @BotFather |
| `OPENAI_API_KEY` | ✅ | Ключ OpenAI |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host:5432/db` |
| `ADMIN_TELEGRAM_IDS` | ✅ | Telegram ID администраторов (через запятую) |
| `PAYMENT_PROVIDER` | — | `stripe` (дефолт) или `yookassa` |
| `PAYMENT_RETURN_URL` | — | URL после оплаты (ссылка на бота) |
| `STRIPE_SECRET_KEY` | при Stripe | `sk_test_...` или `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | при Stripe | `whsec_...` из Stripe CLI / Dashboard |
| `YOOKASSA_SHOP_ID` | при ЮKassa | ID магазина |
| `YOOKASSA_SECRET_KEY` | при ЮKassa | Секретный ключ |
| `ADMIN_WEB_USERNAME` | — | Логин веб-админки (дефолт: `admin`) |
| `ADMIN_WEB_PASSWORD` | — | Пароль веб-админки (дефолт: `changeme`) |
| `OPENAI_MODEL` | — | Дефолтная модель (дефолт: `gpt-4.1-mini`) |
| `RECENT_USER_MESSAGES` | — | Размер окна памяти в парах (дефолт: 10) |

---

## Бэкапы PostgreSQL

```bash
# Разовый дамп
docker compose exec postgres pg_dump -U postgres tg_tutor > backup_$(date +%Y%m%d).sql

# Восстановление
docker compose exec -T postgres psql -U postgres tg_tutor < backup_20260411.sql
```

Настройте cron на VPS для автоматических бэкапов:
```cron
0 3 * * * cd /opt/tg_tutor && docker compose exec postgres pg_dump -U postgres tg_tutor | gzip > /backups/tg_tutor_$(date +\%Y\%m\%d).sql.gz
```
