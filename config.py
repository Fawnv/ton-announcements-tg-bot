import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN в файле .env")

TONAPI_KEY = os.getenv("TONAPI_KEY", "").strip() or None

raw_whitelist = os.getenv("WHITELIST_USER_IDS", "1, 2")
WHITELIST_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in raw_whitelist.split(",")
    if uid.strip().isdigit()
}

# Админы: доступ к /admin (статистика, рассылка, OTA-обновления, настройки).
# Если ADMIN_IDS не задан — админы совпадают с whitelist.
raw_admins = os.getenv("ADMIN_IDS", "") or raw_whitelist
ADMIN_IDS: set[int] = {
    int(uid.strip())
    for uid in raw_admins.split(",")
    if uid.strip().isdigit()
}

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "20"))

# 2328.io — крипто-платежка для подписок (https://2328.io/api)
PAY2328_PROJECT = os.getenv("PAY2328_PROJECT", "").strip() or None
PAY2328_API_KEY = os.getenv("PAY2328_API_KEY", "").strip() or None
# API требует публичный url_callback; бот работает через поллинг /v1/payment/info,
# поэтому сюда можно указать любой валидный публичный URL.
PAY2328_CALLBACK_URL = os.getenv("PAY2328_CALLBACK_URL", "https://2328.io/").strip()

# Запущен ли бот в Docker-контейнере. В Docker код вшит в образ, а переменные
# приходят через env_file, поэтому OTA-обновления и редактор .env отключаются.
IS_DOCKER = (
    os.path.isfile("/.dockerenv")
    or os.getenv("TONANCBOT_IN_DOCKER", "").strip() == "1"
)
