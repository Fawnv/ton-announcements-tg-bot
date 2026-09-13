<div align="center">

# 💎 TON Transaction Tracker & Watchlist Bot

Асинхронный Telegram-бот на **aiogram 3** и **TonAPI (v2)** для отслеживания транзакций в сети TON в реальном времени: вотч-лист кошельков, уведомления о переводах/NFT/стейкинге, обороты, монетизация через Telegram Stars и крипту.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://aiogram.dev/)
[![TonAPI](https://img.shields.io/badge/API-TonAPI%20v2-0098EA)](https://tonapi.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Fawnv/ton-announcements-tg-bot/pulls)
[![GitHub release](https://img.shields.io/github/v/release/Fawnv/ton-announcements-tg-bot?include_prereleases&sort=semver)](https://github.com/Fawnv/ton-announcements-tg-bot/releases)
[![Stars](https://img.shields.io/github/stars/Fawnv/ton-announcements-tg-bot?style=social)](https://github.com/Fawnv/ton-announcements-tg-bot/stargazers)

🤖 **Live Demo:** [@tonancbot](https://t.me/tonancbot)

</div>

---

## ✨ Ключевые возможности

### 🔔 Уведомления о транзакциях в реальном времени
* Нативные переводы **TON** и токены **Jetton** (USDT, NOT, DOGS и др.)
* **NFT-переводы** — с именем и адресом предмета
* **Стейкинг** — пополнение и вывод (`DepositStake` / `WithdrawStake`)
* **Вызовы смарт-контрактов**, где вотч-кошелек — инициатор или контракт
* **Изменение баланса без транзакций** — стейкинг-начисления, nominator pools, награды
* Баланс **ДО / ПОСЛЕ** с индикатором изменения, пересчет в фиат (**USD / EUR / RUB** — переключается тоглом)
* Трекинг доставки исходящих платежей: `⏳ Отправлено` → `✅ Доставлено` автоматически

### 👀 Вотч-лист и аналитика
* Кошельки по адресу (`EQ...`, `UQ...`, `0:...`) или домену (`wallet.ton`, `durov.t.me`)
* **Кастомные имена** кошельков (видны в уведомлениях и списке)
* **Инфо-панель кошелька**: обороты (приход/расход) за сегодня, вчера, неделю, месяц и всё время
* **История транзакций** по кнопке
* Фильтры по минимальной сумме (входящие/исходящие отдельно)
* Удаление только с подтверждением

### 💰 Монетизация
* **Telegram Stars** — встроенная оплата за внутреннюю валюту (`currency="XTR"`)
* **Криптоплатежи через [2328.io](https://2328.io)** — счета в USD, оплата любой криптой (TON, USDT, BTC, ETH, ...), автоматическая активация по поллингу статуса (вебхук-домен не нужен)
* Цены тарифов (в звездах и USD) редактируются админом на лету — без деплоя

### 🛠 Админ-панель (`/admin`)
* 📊 Статистика: пользователи, кошельки, активные подписки, ключи, версия, аптайм
* 👥 Список пользователей с подписками и лимитами (пагинация)
* 📢 Рассылка всем пользователям с превью
* ⚙️ Цены подписок (⭐ и USD)
* 🧩 **Редактор `.env` прямо из бота** (ключи TonAPI/2328, интервалы, whitelist) — секреты маскируются
* 🔄 **OTA-обновления**: проверка новых коммитов и установка с GitHub без SSH (`git pull` + `pip install` + рестарт)
* 🔁 Перезапуск бота

### 🔎 Инлайн-режим (`@bot адрес`)
* Баланс любого кошелька или домена прямо в любом чате
* Защита от спама API при посимвольном наборе, кэширование результатов

### 👥 Система доступа (BYOK)
* **Админы / whitelist:** безлимит, работа на мастер-ключе бота
* **Бесплатные пользователи:** 1 кошелек со своим бесплатным TonAPI-ключом (*Bring Your Own Key* — общие лимиты не выжигаются)
* **Подписчики:** безлимитный вотч-лист

### 🎨 Интерфейс
* Премиум-эмодзи (custom emoji) во всех сообщениях
* Цветные inline-кнопки (`success` / `danger` / `primary`)

---

## 📁 Структура проекта

```text
├── .env.example          # Шаблон конфигурации переменных окружения
├── .gitignore            # Исключения для Git (секреты, база, кэш)
├── Dockerfile            # Сборка контейнера
├── docker-compose.yml    # Запуск бота в Docker
├── requirements.txt      # Зависимости Python
├── config.py             # Загрузка и валидация конфигурации
├── emojis.py             # Премиум-эмодзи (custom emoji)
├── database.py           # Асинхронная работа с SQLite (aiosqlite)
├── ton_api.py            # Клиент TonAPI (аккаунты, транзакции, DNS, курсы)
├── pay2328.py            # Клиент платежного API 2328.io + поллер оплат
├── ota.py                # OTA-обновления из git-репозитория
├── middlewares.py        # Middleware whitelist и авторизации по API-ключу
├── handlers.py           # Хэндлеры команд, FSM, инлайн-режима и платежей
├── admin.py              # Админ-панель (статистика, рассылка, .env, OTA)
├── tracker.py            # Фоновый трекер транзакций и доставки
└── main.py               # Точка входа в приложение
```

---

## 🚀 Быстрый запуск

### Вариант 1: Docker Compose (рекомендуется)

1. **Клонируйте репозиторий:**
   ```bash
   git clone https://github.com/Fawnv/ton-announcements-tg-bot.git
   cd ton-announcements-tg-bot
   ```

2. **Настройте переменные окружения:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   *Укажите `BOT_TOKEN`, `WHITELIST_USER_IDS` и `TONAPI_KEY`.*

3. **Создайте файл базы данных на хосте:**
   ```bash
   touch bot_users.db
   ```

4. **Создайте внешнюю Docker-сеть (если используется `web-network`):**
   ```bash
   docker network create web-network || true
   ```

5. **Соберите и запустите контейнер:**
   ```bash
   docker compose up -d --build
   ```

6. **Просмотр логов:**
   ```bash
   docker compose logs -f
   ```

> 💡 Для OTA-обновлений клонируйте репозиторий на сервере, а не скачивайте архивом — панель админа обновляет бота через `git pull`.

### Вариант 2: Локальный запуск (Python)

1. Требуется **Python 3.11+**.
2. Создайте и активируйте виртуальное окружение:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Для Linux/macOS
   # venv\Scripts\activate   # Для Windows
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Заполните `.env` по примеру `.env.example`.
5. Запустите бота:
   ```bash
   python main.py
   ```

---

## ⚙️ Настройка в Telegram (@BotFather)

1. **Создание бота:**
   * Напишите [@BotFather](https://t.me/BotFather), отправьте `/newbot` и сохраните `BOT_TOKEN`.
2. **Включение инлайн-режима:**
   * Отправьте `/setinline` → выберите бота.
   * В поле **Placeholder** введите: `Введите адрес или домен .ton...`

---

## 🔑 Где получить ключи

* **TonAPI:** зарегистрируйтесь на [tonapi.io](https://tonapi.io) → **TON API → API Keys**. Мастер-ключ — в `TONAPI_KEY`, бесплатные пользователи подключают свои ключи через бота (BYOK).
* **2328.io (для криптооплаты, опционально):** создайте проект на [my.2328.io](https://my.2328.io), скопируйте **Project UUID** и **API key** в `PAY2328_PROJECT` / `PAY2328_API_KEY`. Вебхук-домен не нужен — бот опрашивает статус сам. Если не настроено, кнопка криптооплаты не показывается.

---

## 📋 Основные команды бота

| Команда | Описание |
| :--- | :--- |
| `/start` | Главное меню, статус подписки и лимиты |
| `/watch <адрес/домен>` | Добавить кошелек (или домен `.ton`) в наблюдение |
| `/list` | Вотч-лист, балансы, инфо, история и управление кошельками |
| `/admin` | Админ-панель (только для `ADMIN_IDS`) |
| `/cancel` | Сбросить текущее действие |

### Примеры инлайн-запросов (в любом чате):
* `@your_bot` — карточка своего кошелька из вотч-листа
* `@your_bot UQDNzlh0XSZdb5_Qrlx5QjyZHVAO74v5oMeVVrtF_5Vt1rIt` — карточка по адресу
* `@your_bot wallet.ton` — карточка по домену

---

## 🛠️ Архитектура и безопасность

* **Режим работы:** Long Polling — не требуется белый IP или открытые порты.
* **Надежность данных:** SQLite с автоматической миграцией схемы при обновлениях.
* **Изоляция лимитов:** запросы сторонних пользователей идут через их персональные ключи TonAPI.
* **Защита от дублей:** платежи активируются один раз (идемпотентность по `order_id`).
* **OTA:** обновления применяются `--ff-only` с сохранением локальной БД и `.env`.

---

## 📄 Лицензия

Проект распространяется под лицензией **MIT**. Вы можете свободно модифицировать и использовать его в коммерческих и некоммерческих целях.

---

## 👨‍💻 Автор

* Telegram: [@wr4th](https://t.me/wr4th)
* GitHub: [wr4th](https://github.com/Fawnv)

## 👥 Контрибьюторы

* Telegram: [@l1near](https://t.me/l1near)
* GitHub: [l2near](https://github.com/l2near)

---

## Star History

<a href="https://www.star-history.com/?repos=fawnv%2Fton-announcements-tg-bot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=fawnv/ton-announcements-tg-bot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=fawnv/ton-announcements-tg-bot&type=date&theme=dark&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=fawnv/ton-announcements-tg-bot&type=date&legend=top-left" />
 </picture>
</a>
