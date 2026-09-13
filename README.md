<div align="center">

# 💎 TON Transaction Tracker & Watchlist Bot

Асинхронный Telegram-бот на **aiogram 3** и **TonAPI (v2)** для отслеживания своего кошелька (транзакций на нем).

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://aiogram.dev/)
[![TonAPI](https://img.shields.io/badge/API-TonAPI%20v2-0098EA)](https://tonapi.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Fawnv/ton-announcements-tg-bot/pulls)
[![GitHub release](https://img.shields.io/github/v/release/Fawnv/ton-announcements-tg-bot?include_prereleases&sort=semver)](https://github.com/Fawnv/ton-announcements-tg-bot/releases)
[![Stars](https://img.shields.io/github/stars/Fawnv/ton-announcements-tg-bot?style=social)](https://github.com/Fawnv/ton-announcements-tg-bot/stargazers)

</div>

---

## ✨ Ключевые возможности

### 🔔 Уведомления о транзакциях в реальном времени
* Нативные переводы **TON** и токены **Jetton** (USDT, NOT, DOGS и др.)
* Баланс после транзакции

### 👥 Система доступа
* **Админы / whitelist:** безлимит, работа на мастер-ключе бота
* Остальных бот разворачивает

---

## 📁 Структура проекта

```text
├── .env.example          # Шаблон конфигурации переменных окружения
├── .gitignore            # Исключения для Git (секреты, база, кэш)
├── Dockerfile            # Сборка контейнера
├── docker-compose.yml    # Запуск бота в Docker
├── requirements.txt      # Зависимости Python
├── config.py             # Загрузка и валидация конфигурации, детект Docker
├── database.py           # Асинхронная работа с SQLite (aiosqlite)
├── ton_api.py            # Клиент TonAPI (аккаунты, транзакции, DNS, курсы)
├── middlewares.py        # Middleware whitelist и авторизации по API-ключу
├── handlers.py           # Хэндлеры команд, FSM, инлайн-режима и платежей
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
   * Напишите [@BotFather](https://t.me/BotFather), отправьте `/newbot` и сохраните `BOT_TOKEN`.`

---

## 🔑 Где получить ключи

* **TonAPI:** зарегистрируйтесь на [tonapi.io](https://tonapi.io) → **TON API → API Keys**. Мастер-ключ — в `TONAPI_KEY`
---

## 📋 Основные команды бота

| Команда | Описание |
| :--- | :--- |
| `/start` | Главное меню, статус подписки и лимиты |

---

## 🛠️ Архитектура и безопасность

* **Режим работы:** Long Polling — не требуется белый IP или открытые порты.
* **🐳 Docker-режим:** бот сам определяет запуск в контейнере и отключает неподдерживаемые фичи — OTA-обновления и редактор `.env` (обновление — пересборкой образа, переменные — в docker-compose).
* **Надежность данных:** SQLite с автоматической миграцией схемы при обновлениях.
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
