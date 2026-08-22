# Деплой: GitHub → Railway

## 0. Важная оговорка по данным

Railway размещает сервисы в US / EU / Asia — региона в Казахстане нет. Для MVP и закрытой беты это приемлемый,
но **осознанный** риск: фото детей и так уходят в зарубежные AI-API с согласия родителя, а Railway — тот же класс
трансграничной обработки. Выбираем регион **EU (Amsterdam)**, это фиксируем в политике конфиденциальности,
а перенос БД/S3 в РК (PS Cloud / QazCloud) ставим в реестр техдолга со сроком «до масштабирования рекламы».
Хранилище фото — Cloudflare R2 (S3-совместимое, EU-jurisdiction, бесплатно до 10 ГБ) или MinIO-шаблон Railway.

## 1. GitHub (один раз, с Mac)

```bash
cd ~/Documents/Telegram_stories/storybook
git status                      # репозиторий уже инициализирован и закоммичен
gh auth login                   # если gh не установлен: brew install gh
gh repo create storybook --private --source=. --remote=origin --push
# без gh: создать пустой приватный репо на github.com, затем
# git remote add origin git@github.com:<you>/storybook.git && git push -u origin main
```

## 2. Railway — инфраструктура

В существующем или новом проекте: **+ New → Database → PostgreSQL**, затем **+ New → Database → Redis**.

Хранилище: **+ New → Template → MinIO** (или создать bucket в Cloudflare R2 и взять endpoint/ключи).

## 3. Railway — сервисы из репозитория

Три раза **+ New → GitHub Repo → storybook** (один репозиторий, три сервиса):

| Сервис | Settings → Deploy → Start Command | Нужен ли публичный домен |
|---|---|---|
| `bot` | `python -m storybook bot` | нет (polling) |
| `worker` | `python -m storybook worker` | нет |
| `api` | `python -m storybook api` | да — для вебхука Telegram и callback оплаты (можно позже) |

`railway.toml` в корне уже задаёт Dockerfile и pre-deploy `alembic upgrade head`
(оставьте его только у сервиса `bot`, у остальных очистите Pre-deploy Command, чтобы миграции не бежали трижды).

## 4. Переменные (Settings → Variables, на каждом сервисе или через Shared Variables)

```
SB_BOT_TOKEN=...
SB_ADMIN_IDS=[ваш_tg_id]
SB_ADMIN_CHAT_ID=ваш_tg_id
DATABASE_URL=${{Postgres.DATABASE_URL}}      # reference на сервис Postgres
REDIS_URL=${{Redis.REDIS_URL}}
SB_S3_ENDPOINT=https://<minio-или-r2-endpoint>
SB_S3_BUCKET=storybook
SB_S3_ACCESS_KEY=...
SB_S3_SECRET_KEY=...
SB_PAYMENT_PROVIDER=mock                     # затем kaspi_link / stars
SB_STORY_PROVIDER=mock                       # затем anthropic
SB_IMAGE_PROVIDER=mock                       # затем gemini
SB_ANTHROPIC_API_KEY=
SB_GEMINI_API_KEY=
SB_HUMAN_REVIEW=true
SB_DAILY_AI_BUDGET_KZT=30000
```

Bucket нужно создать один раз (MinIO console или R2 UI); lifecycle-правило на `photos/` — 30 дней.

## 5. Проверка

1. Логи `bot`: `worker_started` / polling без ошибок. Логи `worker`: `worker_started`.
2. В Telegram: `/start` → фото → имя → сюжет → preview → «Заказать» (mock подтверждает сам) → через ~1 мин PDF.
3. `/stats` — воронка должна показать 1 пользователя на каждом шаге.

## 6. Дальше

- Вебхук вместо polling: публичный домен у `api`, `SB_BOT_MODE=webhook`, `SB_WEBHOOK_URL=https://<domain>/tg/webhook`, `SB_WEBHOOK_SECRET=<random>`; сервис `bot` тогда можно выключить.
- CI: GitHub Actions (`.github/workflows/ci.yml`) гоняет тесты на каждый push; Railway деплоит `main` автоматически.
- Бэкапы: Railway Postgres имеет ежедневные снапшоты на платных планах — проверить, что включены.
