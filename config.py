import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Environment variable {name} is required")
    return value.strip()


def _env_int_list(name: str, default: list[int]) -> list[int]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return list(default)

    parsed: list[int] = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            parsed.append(int(item))
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable {name} must contain comma-separated integers"
            ) from exc
    return parsed


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return float(default)
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be float") from exc


def _env_str_list(name: str) -> list[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return []

    items: list[str] = []
    for raw in value.split(","):
        item = raw.strip()
        if item:
            items.append(item)
    return items


BOT_TOKEN = _env_required("BOT_TOKEN")
CRYPTO_BOT_TOKEN = _env_required("CRYPTO_BOT_TOKEN")
NEBIUS_API_KEY = _env_required("NEBIUS_API_KEY")
NEBIUS_API_KEY_SECOND = os.getenv("NEBIUS_API_KEY_SECOND", "").strip()
NEBIUS_API_KEYS = _env_str_list("NEBIUS_API_KEYS")
if not NEBIUS_API_KEYS:
    NEBIUS_API_KEYS = [NEBIUS_API_KEY]
elif NEBIUS_API_KEY not in NEBIUS_API_KEYS:
    NEBIUS_API_KEYS.insert(0, NEBIUS_API_KEY)

if NEBIUS_API_KEY_SECOND and NEBIUS_API_KEY_SECOND not in NEBIUS_API_KEYS:
    NEBIUS_API_KEYS.append(NEBIUS_API_KEY_SECOND)
NEBIUS_URL = os.getenv("NEBIUS_URL", "https://api.studio.nebius.ai/v1/")
AI_MODEL = os.getenv("AI_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
AI_MODEL_DAILY = os.getenv("AI_MODEL_DAILY", AI_MODEL)



YOOMONEY_WALLET = _env_required("YOOMONEY_WALLET")
YOOMONEY_TOKEN = _env_required("YOOMONEY_TOKEN")
YOOMONEY_HTTP_TRUST_ENV = _env_bool("YOOMONEY_HTTP_TRUST_ENV", False)
YOOMONEY_CHECK_CONNECT_TIMEOUT_SEC = _env_float("YOOMONEY_CHECK_CONNECT_TIMEOUT_SEC", 8.0)
YOOMONEY_CHECK_READ_TIMEOUT_SEC = _env_float("YOOMONEY_CHECK_READ_TIMEOUT_SEC", 14.0)
YOOMONEY_CHECK_RETRIES = int(os.getenv("YOOMONEY_CHECK_RETRIES", "3"))
YOOMONEY_CHECK_RETRY_BACKOFF_SEC = _env_float("YOOMONEY_CHECK_RETRY_BACKOFF_SEC", 1.0)
YOOMONEY_CHECK_COOLDOWN_SEC = _env_float("YOOMONEY_CHECK_COOLDOWN_SEC", 20.0)


PRICES_RUB = {
    1: 99,
    7: 199,
    30: 300,
    60: 550,
    90: 800,
    365: 2990,
}


REQUEST_PACKS_RUB = {
    3: 14,
    5: 25,
    10: 50,
    20: 100,
    50: 250,
    100: 500,
}

FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "1"))

VIP_DAILY_LIMIT = int(os.getenv("VIP_DAILY_LIMIT", "200"))

VIP_SLOT_COST_1 = int(os.getenv("VIP_SLOT_COST_1", "1"))
VIP_SLOT_COST_3 = int(os.getenv("VIP_SLOT_COST_3", "2"))
VIP_SLOT_COST_6 = int(os.getenv("VIP_SLOT_COST_6", "4"))
VIP_SLOT_COST_18 = int(os.getenv("VIP_SLOT_COST_18", "12"))

READING_LOCK_ENABLED = _env_bool("READING_LOCK_ENABLED", True)

ANTISPAM_IGNORE_ADMINS = _env_bool("ANTISPAM_IGNORE_ADMINS", False)
CALLBACK_SPAM_WINDOW_SEC = _env_float("CALLBACK_SPAM_WINDOW_SEC", 4.0)
CALLBACK_SPAM_MAX_CLICKS = int(os.getenv("CALLBACK_SPAM_MAX_CLICKS", "8"))
CALLBACK_SPAM_COOLDOWN_SEC = _env_float("CALLBACK_SPAM_COOLDOWN_SEC", 8.0)
CALLBACK_SPAM_MIN_INTERVAL_SEC = _env_float("CALLBACK_SPAM_MIN_INTERVAL_SEC", 0.35)

UPDATE_SPAM_WINDOW_SEC = _env_float("UPDATE_SPAM_WINDOW_SEC", 6.0)
UPDATE_SPAM_MAX_EVENTS = int(os.getenv("UPDATE_SPAM_MAX_EVENTS", "14"))
UPDATE_SPAM_COOLDOWN_SEC = _env_float("UPDATE_SPAM_COOLDOWN_SEC", 10.0)
UPDATE_SPAM_MIN_INTERVAL_SEC = _env_float("UPDATE_SPAM_MIN_INTERVAL_SEC", 0.18)

MESSAGE_SPAM_WINDOW_SEC = _env_float("MESSAGE_SPAM_WINDOW_SEC", 8.0)
MESSAGE_SPAM_MAX_MESSAGES = int(os.getenv("MESSAGE_SPAM_MAX_MESSAGES", "10"))
MESSAGE_SPAM_COOLDOWN_SEC = _env_float("MESSAGE_SPAM_COOLDOWN_SEC", 12.0)
MESSAGE_SPAM_MIN_INTERVAL_SEC = _env_float("MESSAGE_SPAM_MIN_INTERVAL_SEC", 0.5)
MESSAGE_SPAM_DUPLICATE_WINDOW_SEC = _env_float("MESSAGE_SPAM_DUPLICATE_WINDOW_SEC", 12.0)
MESSAGE_SPAM_DUPLICATE_LIMIT = int(os.getenv("MESSAGE_SPAM_DUPLICATE_LIMIT", "3"))

RUB_PER_STAR = _env_float("RUB_PER_STAR", 1.6)

MAILING_RATE_PER_SEC = int(os.getenv("MAILING_RATE_PER_SEC", "25"))
MAILING_BATCH_SIZE = int(os.getenv("MAILING_BATCH_SIZE", "120"))
MAILING_BATCH_PAUSE_SEC = _env_float("MAILING_BATCH_PAUSE_SEC", 1.5)
DAILY_MAILING_TEXT = os.getenv(
    "DAILY_MAILING_TEXT",
    "🌙 Луна подсказывает: время сделать расклад и заглянуть в будущее. 🃏",
).strip()

ADMIN_BROADCAST_RATE_PER_SEC = int(os.getenv("ADMIN_BROADCAST_RATE_PER_SEC", "12"))
ADMIN_BROADCAST_COOLDOWN_SEC = int(os.getenv("ADMIN_BROADCAST_COOLDOWN_SEC", "180"))

PENDING_PAYMENT_TTL_SEC = int(os.getenv("PENDING_PAYMENT_TTL_SEC", "345600"))  # 96 часов
ABANDONED_PAY_REMINDER_1_MIN = int(os.getenv("ABANDONED_PAY_REMINDER_1_MIN", "30"))
ABANDONED_PAY_REMINDER_2_HOURS = int(os.getenv("ABANDONED_PAY_REMINDER_2_HOURS", "24"))
ABANDONED_PAY_REMINDER_3_HOURS = int(os.getenv("ABANDONED_PAY_REMINDER_3_HOURS", "72"))
RETENTION_RATE_PER_SEC = int(os.getenv("RETENTION_RATE_PER_SEC", "8"))


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
)
if not DATABASE_URL:
    raise RuntimeError("Environment variable DATABASE_URL is required")

DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "25"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "50"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

AI_MAX_CONCURRENCY = int(os.getenv("AI_MAX_CONCURRENCY", "24"))
AI_QUEUE_LIMIT = int(os.getenv("AI_QUEUE_LIMIT", "90"))
AI_QUEUE_WAIT_TIMEOUT_SEC = _env_float("AI_QUEUE_WAIT_TIMEOUT_SEC", 4.0)
AI_TIMEOUT_SEC = int(os.getenv("AI_TIMEOUT_SEC", "22"))
AI_TOTAL_TIMEOUT_SEC = int(os.getenv("AI_TOTAL_TIMEOUT_SEC", "28"))
AI_RETRY_COUNT = int(os.getenv("AI_RETRY_COUNT", "0"))
AI_HTTP_TRUST_ENV = _env_bool("AI_HTTP_TRUST_ENV", False)
AI_HTTP_CONNECT_TIMEOUT_SEC = _env_float("AI_HTTP_CONNECT_TIMEOUT_SEC", 8.0)
AI_HTTP_READ_TIMEOUT_SEC = _env_float("AI_HTTP_READ_TIMEOUT_SEC", 24.0)
AI_HTTP_WRITE_TIMEOUT_SEC = _env_float("AI_HTTP_WRITE_TIMEOUT_SEC", 20.0)
AI_HTTP_POOL_TIMEOUT_SEC = _env_float("AI_HTTP_POOL_TIMEOUT_SEC", 2.0)
AI_HTTP_MAX_CONNECTIONS = int(os.getenv("AI_HTTP_MAX_CONNECTIONS", "80"))
AI_HTTP_MAX_KEEPALIVE = int(os.getenv("AI_HTTP_MAX_KEEPALIVE", "40"))

SUB_CACHE_TTL_SEC = int(os.getenv("SUB_CACHE_TTL_SEC", "600"))

REDIS_FSM_URL = os.getenv("REDIS_FSM_URL", "")


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON = _env_bool("LOG_JSON", False)

WEBHOOK_ENABLED = _env_bool("WEBHOOK_ENABLED", False)
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "")

PRICES_USDT = {
    1: 1.5,
    7: 3,
    30: 4,
    60: 7.5,
    90: 10.5,
    365: 38,
}

REQUEST_PACKS_USDT = {
    3: 0.21,
    5: 0.35,
    10: 0.70,
    20: 1.40,
    50: 3.50,
    100: 7.00,
}

CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003779308709")  # Можно юзернейм (например @durov) или ID (-100...)
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/ai_1tarolog")  # Ссылка для кнопки


ADMIN_IDS = _env_int_list("ADMIN_IDS", [6921564778])

NFT_GIFT_CONTACT_USERNAME = os.getenv("NFT_GIFT_CONTACT_USERNAME", "phizer_80").strip()


# Персоны
PERSONAS = {
    "supportive": {
        "name": "💗 Подружка",
        "temp": 0.88,
        "intro": "🔮 <b>Ой, зайка, смотри что карты шепчут:</b>",
        "prompt": """
ТЫ — ЛУЧШАЯ ПОДРУГА КЛИЕНТА. ТВОЯ ЦЕЛЬ — УТЕШИТЬ И ПОДДЕРЖАТЬ.
СТИЛЬ ОБЩЕНИЯ:
1. Используй уменьшительно-ласкательные слова: "зайка", "солнышко", "моя хорошая", "котик".
2. Тон: МАКСИМАЛЬНО тёплый, мягкий, заботливый, эмоциональный.
3. Если карты плохие — смягчай углы! Говори: "Но не переживай, всё наладится", "Вселенная тебя бережет".
4. Никогда не будь грубой. Ты — воплощение эмпатии и любви.
5. Используй эмодзи сердечек и блесток в тексте.
"""
    },
    "sassy": {
        "name": "😈 Стерва",
        "temp": 1.0,
        "intro": "🔮 <b>Ну смотри, что ты натворил(а):</b>",
        "prompt": """
ТЫ — ЦИНИЧНАЯ, ДЕРЗКАЯ И ПРЯМОЛИНЕЙНАЯ ГАДАЛКА.
СТИЛЬ ОБЩЕНИЯ:
1. ТЫ НЕ ЖАЛЕЕШЬ КЛИЕНТА. Твоя задача — снять розовые очки.
2. Используй сарказм, иронию и легкую издёвку.
3. Обращайся на "ТЫ". Не бойся быть резкой.
4. Фразы: "Ну ты даешь", "Хватит ныть", "Карты в шоке от тебя", "Сами виноваты".
5. Если карты плохие — так и говори: "Ну всё, приплыли", "Готовься к проблемам".
6. Не используй сложные слова, говори как уличный психолог.
"""
    },
    "neutral": {
        "name": "⚖️ Эксперт",
        "temp": 0.2,
        "intro": "🔮 <b>Анализ архетипов показал:</b>",
        "prompt": """
ТЫ — СПОКОЙНЫЙ И АНАЛИТИЧНЫЙ ТАРОЛОГ.
СТИЛЬ ОБЩЕНИЯ:
1. Тон: ЯСНЫЙ, СДЕРЖАННЫЙ И ПОНЯТНЫЙ, БЕЗ КАНЦЕЛЯРИТА.
2. Говори НА "ТЫ", но без фамильярности и без сюсюканья.
3. Анализируй символизм карт по делу, не перегружая терминами.
4. Не используй сарказм и не дави эмоциями.
5. Приоритет — четкий вывод и практичные шаги.
"""
    }
}
