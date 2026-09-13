import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN в файле .env")

TONAPI_KEY = os.getenv("TONAPI_KEY", "").strip() or None

raw_tonapi_keys = os.getenv("TONAPI_KEYS", "")
TONAPI_KEYS = [
    key.strip()
    for key in raw_tonapi_keys.split(",")
    if key.strip()
]

if TONAPI_KEY and TONAPI_KEY not in TONAPI_KEYS:
    TONAPI_KEYS.insert(0, TONAPI_KEY)

raw_whitelist = os.getenv("WHITELIST_USER_IDS", "1, 2")
WHITELIST_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in raw_whitelist.split(",")
    if uid.strip().isdigit()
}

raw_admins = os.getenv("ADMIN_IDS", "") or raw_whitelist
ADMIN_IDS: set[int] = {
    int(uid.strip())
    for uid in raw_admins.split(",")
    if uid.strip().isdigit()
}

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "20"))

PAY2328_PROJECT = os.getenv("PAY2328_PROJECT", "").strip() or None
PAY2328_API_KEY = os.getenv("PAY2328_API_KEY", "").strip() or None
PAY2328_CALLBACK_URL = os.getenv("PAY2328_CALLBACK_URL", "https://2328.io/").strip()

IS_DOCKER = (
    os.path.isfile("/.dockerenv")
    or os.getenv("TONANCBOT_IN_DOCKER", "").strip() == "1"
)
