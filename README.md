# storybook — персональная AI-сказка, где ребёнок главный герой

Telegram-бот: фото ребёнка → выбор сюжета → бесплатный preview → оплата → 12-страничная иллюстрированная книга в PDF.
Архитектура: `../architecture.md`, оценка CTO: `../cto-assessment.md`.

## Быстрый старт (локально, без единого API-ключа)

```bash
cp .env.example .env            # вписать SB_BOT_TOKEN и SB_ADMIN_IDS
make up                         # postgres, redis, minio, миграции, бот (polling), worker
make logs
```

В `mock`-режиме (по умолчанию) оплата подтверждается автоматически, иллюстрации — заглушки,
но весь путь `/start → фото → имя → сюжет → preview → оплата → PDF в чат` проходит end-to-end.
Это и есть сквозной «скелет» из плана: сначала убеждаемся, что воронка и очередь работают, потом включаем AI.

## Включение реальных провайдеров

| Переменная | Значения | Что включает |
|---|---|---|
| `SB_STORY_PROVIDER` | `mock` / `anthropic` | текст сказки (Claude, structured JSON + self-review) |
| `SB_IMAGE_PROVIDER` | `mock` / `gemini` | character sheet + иллюстрации (Nano Banana Pro, fallback на flash-модель) |
| `SB_FACE_QA` | `noop` / `insightface` | ArcFace-проверка сходства, ретраи страниц ниже `SB_FACE_THRESHOLD` |
| `SB_PAYMENT_PROVIDER` | `mock` / `kaspi_link` / `stars` | Kaspi-ссылка с ручным подтверждением `/confirm`, либо Telegram Stars |
| `SB_HUMAN_REVIEW` | `true` / `false` | книга идёт админу на `/review` перед отправкой |

InsightFace ставится отдельно: `pip install ".[faceqa]"` (CPU, ~1 ГБ с моделями).

## Прототип сходства (stage-gate)

```bash
mkdir -p proto/photos/child01 && cp ~/photos/*.jpg proto/photos/child01/
SB_IMAGE_PROVIDER=gemini SB_GEMINI_API_KEY=... SB_FACE_QA=insightface \
python scripts/prototype.py --photos proto/photos --out proto/out --scenes 3
```

На выходе `proto/out/<child>/sheet.png`, `scene_N.png` и `report.csv` (face_score, cost, seconds) — для слепой оценки
родителями и заполнения COGS. Go/no-go: ≥ 80 % «узнаю».

## Структура

```
storybook/
  domain/       статусы заказа, инварианты (чистый Python, без I/O)
  content/      сюжеты (YAML, 12 сцен), стиль, текст AI-маркировки
  generation/   StoryGenerator, IllustrationGenerator, FaceQA, бюджетный предохранитель
  rendering/    Jinja2-шаблон книги 210×210 → PDF (Playwright)
  orders/       создание заказа, переходы, идемпотентная отметка оплаты, outbox
  payments/     адаптеры Kaspi-link / Stars / Mock
  storage/      S3 (MinIO), очистка EXIF
  analytics/    события воронки → Postgres (+ PostHog)
  bot/          aiogram 3: FSM пользователя, админ-команды, уведомления
  worker/       pipeline (чистая оркестрация) + arq-задачи (генерация, outbox, напоминания, очистка фото)
  api/          FastAPI: webhook Telegram, callback платёжного агрегатора, /health
migrations/     alembic
scripts/        prototype.py
tests/          домен, контент, платежи, сквозной mock-пайплайн с реальным PDF
```

## Админ-команды

`/confirm <order_id>` — подтвердить оплату Kaspi · `/review <order_id>` — галерея страниц со score и кнопками
«отправить / перегенерировать» · `/regen_page <order_id> <n>` (TODO) · `/stats` — воронка за 7 дней из Postgres.

## Гарантии

- Оплаченный заказ не теряется: `PAID` → outbox (`orders.enqueued_at`) → arq каждые 10 с.
- Задача генерации идемпотентна по `order_id`; каждая стадия и её стоимость — в `jobs`.
- Дневной лимит расходов на AI (`SB_DAILY_AI_BUDGET_KZT`) останавливает генерацию и алертит админа.
- Фото: strip EXIF, хранение в РК (MinIO/S3), lifecycle 30 дней, `/delete_my_data`.
- Маркировка ИИ в боте и в колофоне книги (Закон РК «Об ИИ»).

## Реестр техдолга

| Долг | Срок | Владелец |
|---|---|---|
| Ручное подтверждение Kaspi (`/confirm`) вместо вебхука агрегатора | 50 заказов / 6 недель | основатель |
| `/regen_page` не реализован (только полная перегенерация) | спринт 3 | разработчик |
| Одна VM, без HA; бэкап Postgres — cron на хосте | до 300 книг/мес | разработчик |
| Тексты только RU (kk/en — вынести `bot/texts.py` в бандлы) | после подтверждения гипотезы | — |
| Имя модели Gemini Image — проверить актуальное на дату запуска | перед прототипом | AI-инженер |
| Хостинг Railway (EU) вместо РК-облака — трансграничная обработка фото | до масштабирования рекламы; см. `docs/deploy-railway.md` | основатель + юрист |

## Тесты

`pip install -e ".[dev]" && pytest` — 10 тестов, включая сквозной пайплайн, который рендерит настоящий PDF
через Chromium (в CI нужен `playwright install chromium` или переменная `CHROMIUM_PATH`).

## Деплой

GitHub → Railway: пошагово в [`docs/deploy-railway.md`](docs/deploy-railway.md). `railway.toml` задаёт Dockerfile и миграции перед деплоем.
