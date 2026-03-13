import asyncio
import hashlib
import html
import json
import logging
import random
import re
from collections import OrderedDict
from datetime import datetime
from itertools import count
from time import monotonic
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

import config


def _build_ai_http_client() -> httpx.AsyncClient:
    connect_timeout = max(2.0, float(config.AI_HTTP_CONNECT_TIMEOUT_SEC))
    read_timeout = max(connect_timeout, float(config.AI_HTTP_READ_TIMEOUT_SEC))
    write_timeout = max(2.0, float(config.AI_HTTP_WRITE_TIMEOUT_SEC))
    pool_timeout = max(1.0, float(config.AI_HTTP_POOL_TIMEOUT_SEC))

    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=write_timeout,
        pool=pool_timeout,
    )
    limits = httpx.Limits(
        max_connections=max(4, int(config.AI_HTTP_MAX_CONNECTIONS)),
        max_keepalive_connections=max(2, int(config.AI_HTTP_MAX_KEEPALIVE)),
        keepalive_expiry=30.0,
    )

    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        trust_env=bool(config.AI_HTTP_TRUST_ENV),
    )


def _build_ai_clients() -> list[AsyncOpenAI]:
    raw_keys = getattr(config, "NEBIUS_API_KEYS", [])
    if not isinstance(raw_keys, list):
        raw_keys = [str(config.NEBIUS_API_KEY)]

    keys: list[str] = []
    for raw in raw_keys:
        key = str(raw or "").strip()
        if key and key not in keys:
            keys.append(key)

    if not keys:
        keys = [str(config.NEBIUS_API_KEY)]

    return [
        AsyncOpenAI(
            base_url=config.NEBIUS_URL,
            api_key=api_key,
            max_retries=0,
            http_client=_build_ai_http_client(),
        )
        for api_key in keys
    ]


_ai_clients = _build_ai_clients()
_ai_client_rr_counter = count()


def _next_ai_client_start_index() -> int:
    return next(_ai_client_rr_counter) % len(_ai_clients)


class AIOverloadedError(Exception):
    pass


_ai_semaphore = asyncio.Semaphore(max(1, config.AI_MAX_CONCURRENCY))
_pending_requests = 0
_pending_lock = asyncio.Lock()
_ai_metrics = {
    "requests": 0,
    "retries": 0,
    "queue_rejected": 0,
    "errors": 0,
}
_tarot_response_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
_TAROT_CACHE_TTL_SEC = 6 * 60 * 60
_TAROT_CACHE_MAX_ITEMS = 1500
_TAROT_CACHE_SCHEMA_VERSION = 6
T = TypeVar("T")


def get_ai_runtime_metrics() -> dict[str, int]:
    return {
        "requests": int(_ai_metrics["requests"]),
        "retries": int(_ai_metrics["retries"]),
        "queue_rejected": int(_ai_metrics["queue_rejected"]),
        "errors": int(_ai_metrics["errors"]),
        "pending": int(_pending_requests),
        "max_concurrency": int(config.AI_MAX_CONCURRENCY),
        "queue_limit": int(config.AI_QUEUE_LIMIT),
    }


PERSONA_DEFAULTS = {
    "supportive": {
        "name": "💗 Подружка",
        "prompt": (
            "Ты - мягкий и эмпатичный таролог. Говори тепло, поддерживающе, без давления "
            "и без ложных обещаний."
        ),
        "temp": 0.88,
    },
    "sassy": {
        "name": "😈 Стерва",
        "prompt": (
            "Ты - прямолинейный таролог с легкой дерзостью. Тон уверенный и острый, "
            "но без мата, унижений и токсичности."
        ),
        "temp": 1.0,
    },
    "neutral": {
        "name": "⚖️ Эксперт",
        "prompt": (
            "Ты - аналитичный таролог. Тон спокойный, структурный и деловой, "
            "без драматизации и без официоза. Обращайся на 'ты'."
        ),
        "temp": 0.2,
    },
}


def _clamp_temperature(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.2, parsed))


def _persona_from_config(persona_key: str) -> dict[str, Any]:
    fallback = PERSONA_DEFAULTS.get(persona_key, PERSONA_DEFAULTS["neutral"])
    configured_all = getattr(config, "PERSONAS", {})
    configured = configured_all.get(persona_key, {}) if isinstance(configured_all, dict) else {}

    if not isinstance(configured, dict):
        configured = {}

    name_value = configured.get("name")
    prompt_value = configured.get("prompt")

    name = name_value.strip() if isinstance(name_value, str) and name_value.strip() else fallback["name"]
    prompt = (
        prompt_value.strip()
        if isinstance(prompt_value, str) and prompt_value.strip()
        else fallback["prompt"]
    )
    temp = _clamp_temperature(configured.get("temp"), float(fallback["temp"]))

    return {
        "name": name,
        "prompt": prompt,
        "temp": temp,
    }


PERSONA_UI = {
    "supportive": {
        "badge": "💗 Подружка",
        "analysis_title": "💞 Теплый разбор:",
        "advice_title": "🌿 Мягкий совет:",
    },
    "sassy": {
        "badge": "😈 Стерва",
        "analysis_title": "🧨 Разбор без прикрас:",
        "advice_title": "⚡ Что делать прямо сейчас:",
    },
    "neutral": {
        "badge": "⚖️ Эксперт",
        "analysis_title": "💫 Глубокий анализ:",
        "advice_title": "📜 Совет Вселенной:",
    },
}


ZODIAC_META = {
    "овен": {"element": "fire", "modality": "cardinal"},
    "телец": {"element": "earth", "modality": "fixed"},
    "близнецы": {"element": "air", "modality": "mutable"},
    "рак": {"element": "water", "modality": "cardinal"},
    "лев": {"element": "fire", "modality": "fixed"},
    "дева": {"element": "earth", "modality": "mutable"},
    "весы": {"element": "air", "modality": "cardinal"},
    "скорпион": {"element": "water", "modality": "fixed"},
    "стрелец": {"element": "fire", "modality": "mutable"},
    "козерог": {"element": "earth", "modality": "cardinal"},
    "водолей": {"element": "air", "modality": "fixed"},
    "рыбы": {"element": "water", "modality": "mutable"},
}


ELEMENT_PAIR_BASE = {
    tuple(sorted(("fire", "fire"))): (74, 86, 62),
    tuple(sorted(("earth", "earth"))): (76, 58, 82),
    tuple(sorted(("air", "air"))): (72, 64, 80),
    tuple(sorted(("water", "water"))): (78, 60, 84),
    tuple(sorted(("fire", "air"))): (73, 88, 66),
    tuple(sorted(("earth", "water"))): (80, 62, 86),
    tuple(sorted(("fire", "water"))): (56, 84, 48),
    tuple(sorted(("fire", "earth"))): (60, 68, 54),
    tuple(sorted(("air", "water"))): (63, 70, 58),
    tuple(sorted(("air", "earth"))): (61, 57, 72),
}


TIMEFRAME_KEYWORDS = (
    "когда",
    "срок",
    "сроки",
    "дата",
    "дату",
    "до какого",
    "через сколько",
    "к какому",
    "в каком месяце",
    "в этом месяце",
    "в следующем",
)


BINARY_YES_NO_MARKERS = (
    "да или нет",
    "ответь да или нет",
    "будет ли",
    "получится ли",
    "стоит ли",
    "есть ли",
    "можно ли",
    "удастся ли",
    "смогу ли",
    "буду ли",
    "нужно ли",
    "вернется ли",
    "любит ли",
    "изменяет ли",
    "получу ли",
    "примут ли",
    "возьмут ли",
)


BINARY_CONDITIONAL_STARTERS = (
    "если",
    "если я",
    "если он",
    "если она",
    "если мы",
)


BINARY_OUTCOME_VERBS = (
    "бросит",
    "уйдет",
    "останет",
    "вернет",
    "развед",
    "измен",
    "простит",
    "примет",
    "откаж",
    "получится",
    "удастся",
)


OPEN_QUESTION_STARTERS = (
    "когда",
    "почему",
    "зачем",
    "как",
    "что",
    "какой",
    "какая",
    "какие",
    "где",
    "кто",
    "сколько",
)


HEALTH_KEYWORDS = (
    "здоров",
    "болез",
    "диагноз",
    "операц",
    "врач",
    "больниц",
    "рак",
    "опухол",
    "температур",
    "давлен",
    "сердц",
    "выживет",
)


JOB_KEYWORDS = (
    "работ",
    "оффер",
    "собесед",
    "карьер",
    "ваканс",
    "резюме",
    "hr",
    "рекрутер",
)


RELATION_KEYWORDS = (
    "отнош",
    "бывш",
    "помир",
    "люб",
    "муж",
    "жена",
    "парн",
    "девушк",
    "партнер",
    "партн",
    "мужчин",
    "женщин",
)


PARTNER_PORTRAIT_KEYWORDS = (
    "кто будет моим",
    "кто будет моей",
    "кто мой будущ",
    "будущий парень",
    "будущая девушка",
    "будущий партнер",
    "какой будет партнер",
    "каким будет партнер",
    "как будет выгляд",
    "как выглядит",
    "внешность будущ",
    "внешний типаж будущ",
    "его внешность",
    "ее внешность",
)


PLACE_HINT_KEYWORDS = (
    "где",
    "в каком месте",
    "в каком месте познаком",
    "где познаком",
    "где встр",
    "где искать",
    "где появ",
    "в какой обстановке",
    "в какой локации",
    "место встречи",
    "локац",
    "локаци",
)


QUESTION_SPLIT_TOKENS = (
    "?",
    ";",
    "\n",
)


ROLE_CONTEXT_LABELS: tuple[tuple[str, str], ...] = (
    ("муж", "муже"),
    ("жена", "жене"),
    ("дочь", "дочери"),
    ("сын", "сыне"),
    ("брат", "брате"),
    ("бывш", "бывшем партнере"),
    ("партнер", "партнере"),
    ("парн", "парне"),
    ("девушк", "девушке"),
    ("баб", "другой женщине"),
)


NAME_STOPWORDS = {
    "Ответь",
    "Посадят",
    "Разойдутся",
    "Любит",
    "Вернется",
    "Завидует",
    "Быстро",
    "Какие",
    "Новости",
    "Таро",
    "Карты",
    "Расклад",
    "Итог",
}


MONEY_KEYWORDS = (
    "деньг",
    "доход",
    "финанс",
    "зарплат",
    "прибыл",
    "бюджет",
    "долг",
)


WEAK_PHRASES = (
    "все зависит",
    "при условии",
    "если продолж",
    "активные действия",
    "важно учитывать",
    "может сыграть роль",
    "возможен исход",
    "судьба подсказывает",
    "все уже решено",
    "на уровне энергии",
    "вероятность благоприятного исхода выше средней",
    "сценарий скорее в твою пользу",
    "при ровной тактике",
    "скорее да",
    "скорее нет",
    "ответ ближе к",
)


SOFT_VARIATION_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ситуация", ("картина", "линия событий")),
    ("проявится", ("покажет себя", "станет заметно")),
    ("в ближайшие дни", ("в ближайшем отрезке", "в ближайшее время")),
    ("важно", ("ключево", "существенно")),
    ("в итоге", ("по итогу", "в финале")),
)


INFANTILE_MARKERS = (
    "как кот",
    "котен",
    "обнимаш",
    "лапул",
    "мур",
)


_GRAMMAR_FIXES: tuple[tuple[str, str], ...] = (
    (r"\bтебе будут покупать\b", "тебе купят"),
    (r"\bбудет проявиться\b", "проявится"),
    (r"\bбудут проявиться\b", "проявятся"),
)


COMMON_ENGLISH_REPLACEMENTS = {
    "tomorrow": "завтра",
    "today": "сегодня",
    "tonight": "сегодня вечером",
    "next": "следующий",
    "week": "неделя",
    "weeks": "недели",
    "month": "месяц",
    "months": "месяцы",
    "day": "день",
    "days": "дни",
}


_EMOJI_CHAR_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]"
)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> str:
    cleaned = _strip_code_fences(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]

    raise ValueError("JSON object not found")


def _response_preview(text: str, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def _ensure_text(value: Any, fallback: str) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else fallback
    return fallback


def _ensure_rich_text(value: Any, fallback: str, min_words: int) -> str:
    text = _ensure_text(value, fallback)
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    return text if len(words) >= min_words else fallback


def _contains_forbidden_script(text: str) -> bool:
    for char in text:
        code = ord(char)
        if (
            0x3040 <= code <= 0x30FF  # Hiragana / Katakana
            or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= code <= 0x4DBF  # CJK Extension A
            or 0xAC00 <= code <= 0xD7AF  # Hangul
        ):
            return True
    return False


def _is_russian_like_text(text: str, min_ratio: float = 0.55) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return True
    cyr = re.findall(r"[А-Яа-яЁё]", text)
    return (len(cyr) / max(1, len(letters))) >= min_ratio


def _replace_common_english_tokens(text: str) -> str:
    if not text:
        return text

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(key) for key in COMMON_ENGLISH_REPLACEMENTS) + r")\b",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = COMMON_ENGLISH_REPLACEMENTS.get(token.lower(), "")
        if token[:1].isupper() and replacement:
            return replacement[:1].upper() + replacement[1:]
        return replacement

    return pattern.sub(repl, text)


def _remove_remaining_latin_words(text: str) -> str:
    cleaned = re.sub(r"[A-Za-z]+[A-Za-z0-9_'-]*", "", text)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([\(\[\{])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([\)\]\}])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _limit_emojis_per_paragraph(text: str, max_emojis: int = 1) -> str:
    if not text:
        return text

    limited_lines: list[str] = []
    for line in text.split("\n"):
        line_emojis = [match.group(0) for match in _EMOJI_CHAR_RE.finditer(line)]

        normalized = "".join(ch for ch in line if not _EMOJI_CHAR_RE.fullmatch(ch))
        normalized = normalized.replace("\ufe0f", "").replace("\u200d", "")
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()

        if line_emojis and max_emojis > 0 and normalized:
            keep_emoji = line_emojis[0]
            normalized = f"{normalized} {keep_emoji}".strip()

        limited_lines.append(normalized)

    return "\n".join(limited_lines).strip()


def _sanitize_russian_text(value: Any, fallback: str, min_words: int = 3) -> str:
    text = _ensure_text(value, fallback)
    text = _replace_common_english_tokens(text)

    if _contains_forbidden_script(text):
        text = "".join(
            ch
            for ch in text
            if not (
                0x3040 <= ord(ch) <= 0x30FF
                or 0x4E00 <= ord(ch) <= 0x9FFF
                or 0x3400 <= ord(ch) <= 0x4DBF
                or 0xAC00 <= ord(ch) <= 0xD7AF
            )
        ).strip()

    text = _remove_remaining_latin_words(text)

    if not _is_russian_like_text(text):
        return fallback

    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if len(words) < min_words:
        return fallback
    return _limit_emojis_per_paragraph(text, max_emojis=1)


def _needs_timeframe(question: str) -> bool:
    q = question.lower()
    return any(keyword in q for keyword in TIMEFRAME_KEYWORDS)


def _extract_question_items(question: str) -> list[str]:
    raw = (question or "").replace("\r", "\n").strip()
    if not raw:
        return []

    prepared = re.sub(r"(?m)^\s*[\-•]+\s*", "", raw)
    prepared = re.sub(r"(?m)^\s*\d+[\)\.\-:]\s*", "", prepared)
    prepared = re.sub(r"(?i)^\s*ответь\s+на\s+все\s+мои\s+вопросы[^:]{0,120}:\s*", "", prepared)
    prepared = re.sub(r"(?i)^\s*вопросы\s*[:\-]\s*", "", prepared)

    chunks: list[str] = []
    if "?" in prepared or "？" in prepared:
        chunks.extend(re.split(r"[?？]+", prepared))
    else:
        chunks.extend(re.split(r"(?:\n+|;)", prepared))

    cleaned: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        item = re.sub(r"\s+", " ", chunk).strip(" .,:;!?-\n\t")
        if not item:
            continue
        words = re.findall(r"\w+", item, flags=re.UNICODE)
        if len(words) < 2:
            continue

        normalized = item.lower().replace("ё", "е")
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(item)

    return cleaned if cleaned else [re.sub(r"\s+", " ", raw).strip()]


def extract_tarot_questions(question: str) -> list[str]:
    return _extract_question_items(question)


def _is_binary_question(question: str) -> bool:
    q = question.lower().replace("ё", "е")
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return False

    if any(marker in q for marker in BINARY_YES_NO_MARKERS):
        return True

    if any(q.startswith(starter) for starter in BINARY_CONDITIONAL_STARTERS):
        return True

    first_word = q.split(" ", 1)[0]
    if first_word in OPEN_QUESTION_STARTERS:
        return False

    if any(verb in q for verb in BINARY_OUTCOME_VERBS):
        return True

    return bool(re.search(r"\bли\b", q))


def _is_health_question(question: str) -> bool:
    q = question.lower().replace("ё", "е")
    return any(keyword in q for keyword in HEALTH_KEYWORDS)


def _is_pregnancy_question(question: str) -> bool:
    q = question.lower().replace("ё", "е")
    markers = (
        "беремен",
        "зачат",
        "овуля",
        "задерж",
        "месячн",
        "хгч",
    )
    return any(marker in q for marker in markers)


def _question_topic(question: str, is_health: bool) -> str:
    if is_health:
        return "health"

    q = question.lower().replace("ё", "е")
    if any(keyword in q for keyword in JOB_KEYWORDS):
        return "job"
    if any(keyword in q for keyword in RELATION_KEYWORDS):
        return "relationship"
    if any(keyword in q for keyword in MONEY_KEYWORDS):
        return "money"
    return "general"


def _needs_partner_portrait(question: str) -> bool:
    q = question.lower().replace("ё", "е")
    if any(marker in q for marker in ("завид", "ревну", "сравнива")):
        return False

    if any(marker in q for marker in PARTNER_PORTRAIT_KEYWORDS):
        return True

    has_relation_context = any(keyword in q for keyword in RELATION_KEYWORDS)
    has_portrait_intent = any(marker in q for marker in ("кто", "какой", "каким", "как выгляд"))
    has_appearance_marker = any(marker in q for marker in ("внешност", "типаж", "внешне"))

    if has_relation_context and has_portrait_intent and has_appearance_marker:
        return True

    return False


def _needs_place_hint(question: str) -> bool:
    q = question.lower().replace("ё", "е")
    return any(marker in q for marker in PLACE_HINT_KEYWORDS)


def _has_weak_phrases(text: str, allow_infantile: bool = False) -> bool:
    low = text.lower().replace("ё", "е")
    if any(phrase in low for phrase in WEAK_PHRASES):
        return True
    if not allow_infantile and any(marker in low for marker in INFANTILE_MARKERS):
        return True
    return False


def _strip_forced_yes_no_prefix(text: str, fallback: str, is_binary_question: bool) -> str:
    if is_binary_question:
        return text

    cleaned = re.sub(
        r"^\s*(?:да|нет|скорее да|скорее нет)\s*[:,-]?\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^[\-–—:,.\s]+", "", cleaned).strip()
    words = re.findall(r"\w+", cleaned, flags=re.UNICODE)
    if len(words) < 3:
        return fallback
    return cleaned


def _polish_tarot_russian(text: str) -> str:
    polished = str(text or "")
    for pattern, replacement in _GRAMMAR_FIXES:
        polished = re.sub(pattern, replacement, polished, flags=re.IGNORECASE)
    polished = re.sub(r"\s{2,}", " ", polished).strip()
    return polished


def _soft_variate_text(text: str, chance: float = 0.1) -> str:
    value = str(text or "")
    if not value:
        return value

    for source, alternatives in SOFT_VARIATION_MAP:
        if source.lower() not in value.lower():
            continue
        if random.random() > chance:
            continue

        replacement = random.choice(alternatives)
        value = re.sub(re.escape(source), replacement, value, count=1, flags=re.IGNORECASE)

    return value


def _is_direct_yes_no(text: str) -> bool:
    return bool(re.match(r"^\s*(?:да|нет)\b", str(text or "").lower().replace("ё", "е")))


def _card_anchor_phrase(cards_data: list[dict[str, Any]]) -> str:
    if not cards_data:
        return "по текущей связке"

    first_name = _sanitize_russian_text(cards_data[0].get("name"), "первой карте", min_words=1)
    if len(cards_data) < 2:
        return f"по карте {first_name}"

    second_name = _sanitize_russian_text(cards_data[1].get("name"), "второй карте", min_words=1)
    return f"по связке {first_name} и {second_name}"


def _binary_outcome_bias(cards_data: list[dict[str, Any]]) -> int:
    if not cards_data:
        return 0

    positive_markers = ("солнце", "звезда", "туз", "императрица", "мир", "влюблен")
    negative_markers = ("башня", "дьявол", "луна", "десятка мечей", "пятерка мечей")

    score = 0
    for card in cards_data[:2]:
        name = str(card.get("name") or "").lower().replace("ё", "е")
        if any(marker in name for marker in positive_markers):
            score += 1
        if any(marker in name for marker in negative_markers):
            score -= 1
        if bool(card.get("is_reversed")):
            score -= 1

    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def _fallback_verdict_text(
    question: str,
    cards_data: list[dict[str, Any]],
    *,
    is_health: bool,
    is_binary_question: bool,
    need_partner_portrait: bool,
    need_place_hint: bool,
) -> str:
    anchor = _card_anchor_phrase(cards_data)
    topic = _question_topic(question, is_health)
    q = question.lower().replace("ё", "е")

    if need_partner_portrait:
        return (
            f"{anchor.capitalize()} проявляется партнер с внутренним стержнем и спокойной уверенностью: "
            "он будет сближаться через поступки, а не через красивые обещания."
        )
    if need_place_hint:
        return (
            f"{anchor.capitalize()} знакомство вероятнее в живой городской среде: "
            "там, где есть движение, короткие контакты и естественный повод заговорить."
        )
    if is_binary_question:
        bias = _binary_outcome_bias(cards_data)
        if topic == "relationship" and any(marker in q for marker in ("брос", "уйд", "развед")):
            if bias > 0:
                return (
                    "Да: риск разрыва повышен, если разговор пойдет по старому конфликтному сценарию "
                    "без договоренностей."
                )
            if bias < 0:
                return (
                    "Нет: полного ухода по картам не видно, но эмоциональная дистанция возможна, "
                    "если копить обиды."
                )
            return "Нет, но с напряженными качелями: многое решит тон ближайшего диалога."

        if "новост" in q:
            if bias > 0:
                return (
                    "Да: новости придут быстро, и по характеру они будут активными - с конкретным движением "
                    "по ситуации."
                )
            if bias < 0:
                return (
                    "Нет: быстрых новостей по картам не видно; информация будет поступать медленнее и фрагментами."
                )
            return (
                "Да: новости ожидаются в ближайший период, но сначала они будут частичными и потребуют уточнения."
            )

        if bias > 0:
            return "Да: по картам окно возможности открыто, и шанс высокий уже в ближайшем цикле."
        if bias < 0:
            return (
                "Нет на текущем этапе: пока энергии недостаточно для устойчивого подтверждения, "
                "нужна дополнительная проверка по фактам."
            )
        return "Да, но с нюансами: нужна проверка реальных сигналов в ближайшие дни."

    if topic == "relationship":
        return f"{anchor.capitalize()} линия отношений развивается постепенно: сначала прояснение, затем устойчивое сближение."
    if topic == "job":
        return f"{anchor.capitalize()} карьерный вектор рабочий: шанс на движение вверх есть уже в ближайшем периоде."
    if topic == "money":
        return f"{anchor.capitalize()} финансовая динамика выравнивается: ближайший цикл дает шанс на ощутимый плюс."
    if topic == "health":
        return f"{anchor.capitalize()} указывает на постепенную стабилизацию состояния без резких скачков."
    return f"{anchor.capitalize()} сценарий складывается в твою пользу при сохранении ровного темпа и фокуса."


def _fallback_result_text(
    question: str,
    cards_data: list[dict[str, Any]],
    *,
    is_health: bool,
    is_binary_question: bool,
    need_partner_portrait: bool,
    need_place_hint: bool,
) -> str:
    anchor = _card_anchor_phrase(cards_data)
    topic = _question_topic(question, is_health)
    q = question.lower().replace("ё", "е")

    if need_partner_portrait:
        return (
            f"Итог: {anchor} показывает перспективу знакомства с человеком зрелого характера. "
            "Связь будет раскрываться через регулярные проявления и понятную инициативу."
        )
    if need_place_hint:
        return (
            f"Итог: {anchor} ведет к знакомству через активную среду и повторяемые точки присутствия. "
            "Чем чаще ты бываешь в таких местах, тем выше шанс нужного контакта."
        )
    if is_binary_question:
        bias = _binary_outcome_bias(cards_data)
        if topic == "relationship" and any(marker in q for marker in ("брос", "уйд", "развед")):
            if bias > 0:
                return (
                    "Итог: разрыв вероятен, если не выстроить спокойные правила общения в ближайшие дни."
                )
            if bias < 0:
                return (
                    "Итог: окончательного ухода не видно; связь напряженная, но ресурс на сохранение отношений есть."
                )
            return "Итог: сценарий пограничный; исход решится по качеству ближайшего разговора и взаимных границ."

        if "новост" in q:
            if bias > 0:
                return (
                    "Итог: новости придут быстро и будут с практической ценностью - про конкретные шаги и продвижение "
                    "по ситуации."
                )
            if bias < 0:
                return (
                    "Итог: быстрых новостей не ожидается; сначала появятся косвенные сигналы, потом подтверждение."
                )
            return (
                "Итог: новости будут, но сначала в неполном виде; картина соберется по мере уточнений."
            )

        if bias > 0:
            return "Итог: тенденция положительная, подтверждение вероятнее в ближайшее время при проверке по фактам."
        if bias < 0:
            return "Итог: сейчас подтверждение маловероятно; ситуация требует паузы и повторной проверки чуть позже."
        return "Итог: картина промежуточная; окончательный ответ проявится после дополнительного уточнения по фактам."

    if topic == "relationship":
        return "Итог: связь имеет потенциал и будет укрепляться через спокойный, последовательный контакт."
    if topic == "job":
        return "Итог: рабочий сценарий реалистичен, а ключевой сдвиг проявится через конкретные действия в ближайший период."
    if topic == "money":
        return "Итог: финансовый вектор разворачивается в плюс, если удержать дисциплину и не распылять ресурс."
    if topic == "health":
        return "Итог: по картам приоритет - постепенная стабилизация и контроль динамики в ближайшем периоде."
    return "Итог: базовый тренд благоприятный; при ровной тактике ты получишь ощутимый сдвиг по ситуации."


def _fallback_analysis_text(cards_data: list[dict[str, Any]]) -> str:
    if not cards_data:
        return (
            "Ситуация развивается волнообразно: ключ к результату в спокойной последовательности действий. "
            "Сейчас важно не дергаться на каждом сигнале, а удерживать курс и проверять прогресс по фактам."
        )

    names: list[str] = []
    for card in cards_data[:8]:
        name = _sanitize_russian_text(card.get("name"), "карта", min_words=1)
        names.append(name)

    lead = ", ".join(names[:4]) if len(names) >= 4 else ", ".join(names)
    support = ", ".join(names[4:8]) if len(names) > 4 else ""

    if len(cards_data) >= 18:
        core = (
            f"В центральной линии расклада выделяются {lead}: через них видно, что процесс идет в несколько этапов, "
            "где сначала проявляются внутренние противоречия, а затем формируется более устойчивый вектор."
        )
        if support:
            core += (
                f" Дополнительный слой дают {support}: они уточняют, где есть риск отката и где, наоборот, "
                "сценарий можно закрепить через последовательные действия и контроль реальных сигналов."
            )
        core += " Это не одномоментный поворот, а постепенная развязка с ясной фазой прояснения."
        return core

    return (
        f"Ключевая связка расклада проходит через {lead}: по ней видно постепенное движение от неопределенности "
        "к более понятной конфигурации ситуации. "
        "В ближайшем шаге обычно сначала проявляется внутренний мотив участников, а уже потом видимый результат. "
        "Поэтому здесь важно считывать не один эпизод, а повторяемую линию поведения."
    )


def _fallback_extension_impact(cards_data: list[dict[str, Any]], added_cards_count: int) -> str:
    safe_added = max(1, int(added_cards_count))
    extra_cards = cards_data[-safe_added:] if cards_data else []
    names = ", ".join(
        _sanitize_russian_text(card.get("name"), "карта", min_words=1)
        for card in extra_cards
        if isinstance(card, dict)
    )
    if not names:
        names = "докинутые карты"

    return (
        f"Докид через {names} сместил акцент расклада: картина стала более предметной, "
        "появились уточнения по рискам и по ближайшему сценарию развития. "
        "Это не отмена базового расклада, а его донастройка с более точными ориентирами."
    )


def _ensure_analysis_card_references(analysis: str, cards_data: list[dict[str, Any]]) -> str:
    if not cards_data:
        return analysis

    normalized_analysis = analysis.lower().replace("ё", "е")
    referenced = 0
    for card in cards_data:
        name = str(card.get("name") or "").strip().lower().replace("ё", "е")
        if name and name in normalized_analysis:
            referenced += 1

    if referenced >= 2:
        return analysis

    first = cards_data[0] if cards_data else {}
    second = cards_data[1] if len(cards_data) > 1 else None
    first_name = _sanitize_russian_text(first.get("name"), "первая карта", min_words=1)
    if second is None:
        bridge = (
            f" По линии карт это хорошо видно через {first_name}: "
            "сценарий будет проявляться последовательно, без резких разворотов."
        )
    else:
        second_name = _sanitize_russian_text(second.get("name"), "вторая карта", min_words=1)
        bridge = (
            f" По линии карт это подтверждают {first_name} и {second_name}: "
            "сначала проявится скрытая динамика, затем ситуация перейдет в более понятную фазу."
        )
    return (analysis + bridge).strip()


def _clamp_percent_range(value: int, low: int = 40, high: int = 92) -> int:
    return max(low, min(high, int(value)))


def _normalized_sign_key(sign: str) -> str:
    return sign.strip().lower().replace("ё", "е")


def _pair_jitter(sign1: str, sign2: str, salt: int) -> int:
    pair = "|".join(sorted((_normalized_sign_key(sign1), _normalized_sign_key(sign2))))
    checksum = sum(ord(char) for char in f"{pair}:{salt}")
    return (checksum % 7) - 3


def _zodiac_scores(sign1: str, sign2: str) -> tuple[int, int, int]:
    key1 = _normalized_sign_key(sign1)
    key2 = _normalized_sign_key(sign2)
    meta1 = ZODIAC_META.get(key1)
    meta2 = ZODIAC_META.get(key2)
    if not meta1 or not meta2:
        return 66, 64, 68

    pair_key = tuple(sorted((meta1["element"], meta2["element"])))
    base_love, base_passion, base_understanding = ELEMENT_PAIR_BASE.get(pair_key, (66, 64, 68))

    if meta1["modality"] == meta2["modality"]:
        base_love += 2
        base_understanding += 2
        base_passion -= 1

    if key1 == key2:
        base_love += 3
        base_understanding += 4
        base_passion -= 2

    love = _clamp_percent_range(base_love + _pair_jitter(sign1, sign2, 1))
    passion = _clamp_percent_range(base_passion + _pair_jitter(sign1, sign2, 2))
    understanding = _clamp_percent_range(base_understanding + _pair_jitter(sign1, sign2, 3))
    return love, passion, understanding


def _relationship_energy_text(love: int, passion: int, understanding: int) -> str:
    average = int((love + passion + understanding) / 3)
    spread = max(love, passion, understanding) - min(love, passion, understanding)

    if average >= 78 and spread <= 14:
        return "Гармоничный союз с сильной взаимной поддержкой и хорошим балансом чувств."
    if passion >= 80 and understanding <= 58:
        return "Взрывное притяжение: химия сильная, но важно учиться договариваться без драм."
    if understanding >= 78 and passion <= 60:
        return "Спокойный зрелый союз: много надежности и уважения, страсть раскрывается постепенно."
    if average >= 70:
        return "Перспективная пара: при честном диалоге отношения могут быстро выйти на высокий уровень."
    if average >= 58:
        return "Контрастный союз: потенциал есть, но нужны терпение, правила общения и бытовой баланс."
    return "Непростая связка: потребуется много осознанности, чтобы сохранить тепло и не копить обиды."


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _normalize_question_for_cache(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def _cards_signature(cards_data: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for card in cards_data:
        card_id = str(card.get("id") or card.get("name") or "")
        position = "r" if bool(card.get("is_reversed")) else "u"
        parts.append(f"{card_id}:{position}")
    return "|".join(parts)


def _tarot_cache_key(
    question: str,
    cards_data: list[dict[str, Any]],
    persona_key: str,
    length_setting: str,
    extension_mode: bool,
    added_cards_count: int,
) -> str:
    payload = (
        f"v={_TAROT_CACHE_SCHEMA_VERSION};"
        f"q={_normalize_question_for_cache(question)};"
        f"cards={_cards_signature(cards_data)};"
        f"persona={persona_key};"
        f"length={length_setting};"
        f"ext={int(extension_mode)};"
        f"added={added_cards_count}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_transient_tarot_response(text: str) -> bool:
    normalized = (text or "").lower()
    markers = (
        "сервис перегружен",
        "связь с космосом прервана",
        "попробуйте снова через",
        "попробуйте позже",
        "слишком много карт",
    )
    return any(marker in normalized for marker in markers)


def _cache_get_tarot_response(cache_key: str) -> str | None:
    cached = _tarot_response_cache.get(cache_key)
    if not cached:
        return None

    created_at, value = cached
    if monotonic() - created_at > _TAROT_CACHE_TTL_SEC:
        _tarot_response_cache.pop(cache_key, None)
        return None

    _tarot_response_cache.move_to_end(cache_key)
    return value


def _cache_put_tarot_response(cache_key: str, value: str) -> None:
    if not value or _is_transient_tarot_response(value):
        return

    _tarot_response_cache[cache_key] = (monotonic(), value)
    _tarot_response_cache.move_to_end(cache_key)

    while len(_tarot_response_cache) > _TAROT_CACHE_MAX_ITEMS:
        _tarot_response_cache.popitem(last=False)


def _attempt_timeout_sec(attempt: int, max_attempts: int, max_tokens: int) -> int:
    configured_timeout = max(10, int(config.AI_TIMEOUT_SEC))
    token_based_timeout = 8 + max(0, int(max_tokens / 160))
    base_timeout = min(45, max(configured_timeout, max(8, token_based_timeout)))
    if max_attempts <= 1:
        return base_timeout

    decayed_timeout = int(base_timeout * (0.7 ** (attempt - 1)))
    return max(8, decayed_timeout)


def _attempt_max_tokens(max_tokens: int, attempt: int) -> int:
    if attempt <= 1:
        return max_tokens

    reduced_tokens = int(max_tokens * (0.72 ** (attempt - 1)))
    return max(160, min(max_tokens, reduced_tokens))


def _total_timeout_budget_sec(first_attempt_timeout: int, max_attempts: int) -> int:
    attempts_overhead = 1.1 + max(0, max_attempts - 1) * 0.1
    calculated_budget = int(first_attempt_timeout * attempts_overhead)
    configured_cap = max(10, int(getattr(config, "AI_TOTAL_TIMEOUT_SEC", 28)))
    return max(10, min(calculated_budget, configured_cap))


def _retry_error_kind(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, APITimeoutError):
        return "api_timeout"
    if isinstance(exc, APIConnectionError):
        return "connection"
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.ProxyError):
        return "proxy"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, APIError):
        status_code = getattr(exc, "status_code", None)
        return f"api_{status_code or 'error'}"
    return exc.__class__.__name__.lower()


def _is_model_not_found_error(exc: Exception) -> bool:
    if not isinstance(exc, APIError):
        return False
    status_code = getattr(exc, "status_code", None)
    if status_code != 404:
        return False
    message = str(exc).lower()
    return "does not exist" in message or "model" in message


async def _create_completion(
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    model: str | None = None,
) -> str:
    max_attempts = max(1, min(config.AI_RETRY_COUNT + 1, 4))
    start_client_index = _next_ai_client_start_index()
    clients_count = len(_ai_clients)
    started_at = asyncio.get_running_loop().time()
    first_attempt_timeout = _attempt_timeout_sec(1, max_attempts, max_tokens)
    total_budget_sec = _total_timeout_budget_sec(first_attempt_timeout, max_attempts)

    for attempt in range(1, max_attempts + 1):
        elapsed_sec = asyncio.get_running_loop().time() - started_at
        remaining_budget_sec = total_budget_sec - elapsed_sec
        if remaining_budget_sec <= 0:
            _ai_metrics["errors"] += 1
            raise asyncio.TimeoutError("AI request total timeout budget exceeded")

        attempt_timeout_sec = min(
            _attempt_timeout_sec(attempt, max_attempts, max_tokens),
            max(1, int(remaining_budget_sec)),
        )
        attempt_max_tokens = _attempt_max_tokens(max_tokens, attempt)
        client_index = (start_client_index + attempt - 1) % clients_count
        active_client = _ai_clients[client_index]

        try:
            model_name = (model or config.AI_MODEL).strip() or config.AI_MODEL
            completion = await asyncio.wait_for(
                active_client.chat.completions.create(
                    model=model_name,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    top_p=0.9,
                    max_tokens=attempt_max_tokens,
                ),
                timeout=attempt_timeout_sec,
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            retryable = isinstance(
                exc,
                (
                    asyncio.TimeoutError,
                    APITimeoutError,
                    APIConnectionError,
                    RateLimitError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.ConnectError,
                    httpx.ProxyError,
                ),
            ) or (isinstance(exc, APIError) and status_code in {429, 500, 502, 503, 504})

            if attempt >= max_attempts or not retryable:
                _ai_metrics["errors"] += 1
                raise

            backoff_sec = min(2 ** (attempt - 1), 1)
            _ai_metrics["retries"] += 1
            logging.warning(
                (
                    "AI request retrying in %ss (attempt %s/%s, timeout=%ss, "
                    "max_tokens=%s, key_slot=%s/%s, kind=%s): %s"
                ),
                backoff_sec,
                attempt,
                max_attempts,
                attempt_timeout_sec,
                attempt_max_tokens,
                client_index + 1,
                clients_count,
                _retry_error_kind(exc),
                exc,
            )

            elapsed_after_error = asyncio.get_running_loop().time() - started_at
            remaining_after_error = total_budget_sec - elapsed_after_error
            if remaining_after_error <= 1:
                _ai_metrics["errors"] += 1
                raise

            await asyncio.sleep(min(backoff_sec, max(0, remaining_after_error - 1)))

    raise RuntimeError("Unreachable retry state")


async def _reserve_queue_slot() -> bool:
    global _pending_requests
    async with _pending_lock:
        if _pending_requests >= max(1, config.AI_QUEUE_LIMIT):
            return False
        _pending_requests += 1
        return True


async def _release_queue_slot() -> None:
    global _pending_requests
    async with _pending_lock:
        _pending_requests = max(0, _pending_requests - 1)


async def _run_ai_with_limits(call: Callable[[], Awaitable[T]]) -> T:
    reserved = await _reserve_queue_slot()
    if not reserved:
        _ai_metrics["queue_rejected"] += 1
        raise AIOverloadedError("AI queue limit exceeded")

    acquired = False
    try:
        _ai_metrics["requests"] += 1
        wait_timeout = max(2.0, float(config.AI_QUEUE_WAIT_TIMEOUT_SEC))
        try:
            await asyncio.wait_for(_ai_semaphore.acquire(), timeout=wait_timeout)
            acquired = True
        except asyncio.TimeoutError as exc:
            _ai_metrics["queue_rejected"] += 1
            logging.warning(
                "AI queue wait timeout pending=%s max_concurrency=%s wait_timeout=%.1fs",
                _pending_requests,
                config.AI_MAX_CONCURRENCY,
                wait_timeout,
            )
            raise AIOverloadedError("AI concurrency wait timeout") from exc

        return await call()
    finally:
        if acquired:
            _ai_semaphore.release()
        await _release_queue_slot()


async def _request_json_with_repair(
    base_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    max_attempts: int = 1,
    model: str | None = None,
) -> dict[str, Any]:
    raw_response = ""

    for attempt in range(1, max_attempts + 1):
        messages = list(base_messages)
        if raw_response:
            messages.append(
                {
                    "role": "assistant",
                    "content": raw_response,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Предыдущий ответ невалидный. Верни строго валидный JSON-объект "
                        "без markdown, без пояснений и без лишнего текста."
                    ),
                }
            )

        raw_response = await _create_completion(
            messages,
            temperature,
            max_tokens,
            model=model,
        )

        try:
            json_candidate = _extract_json_object(raw_response)
            return json.loads(json_candidate)
        except Exception as exc:
            logging.warning(
                "AI JSON parse failed on attempt %s: %s | preview=%s",
                attempt,
                exc,
                _response_preview(raw_response),
            )

    raise ValueError("Could not obtain valid JSON from model")


async def _request_json_with_limits(
    base_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    max_attempts: int = 1,
    model: str | None = None,
) -> dict[str, Any]:
    adaptive_attempts = max(1, int(max_attempts))
    if _pending_requests > max(8, int(config.AI_MAX_CONCURRENCY)):
        adaptive_attempts = 1

    return await _run_ai_with_limits(
        lambda: _request_json_with_repair(
            base_messages=base_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            max_attempts=adaptive_attempts,
            model=model,
        )
    )


def _build_tarot_html(
    payload: dict[str, Any],
    question: str,
    question_items: list[str],
    cards_count: int,
    cards_data: list[dict[str, Any]],
    persona_key: str,
    need_timeframe: bool,
    is_health: bool,
    is_binary_question: bool,
    need_partner_portrait: bool,
    need_place_hint: bool,
    extension_mode: bool,
    added_cards_count: int,
) -> str:
    analysis_fallback = _fallback_analysis_text(cards_data)
    _ = _sanitize_russian_text(payload.get("intro"), "Анализ ситуации по картам таро", min_words=3)
    analysis_min_words = 18 if extension_mode else 10
    analysis = _sanitize_russian_text(
        payload.get("analysis"),
        analysis_fallback,
        min_words=analysis_min_words,
    )
    verdict_fallback = _fallback_verdict_text(
        question,
        cards_data,
        is_health=is_health,
        is_binary_question=is_binary_question,
        need_partner_portrait=need_partner_portrait,
        need_place_hint=need_place_hint,
    )
    verdict = _sanitize_russian_text(payload.get("verdict"), verdict_fallback, min_words=6)
    verdict = _strip_forced_yes_no_prefix(verdict, verdict_fallback, is_binary_question)
    if is_binary_question and not _is_direct_yes_no(verdict):
        verdict = verdict_fallback
    timeframe_fallback = (
        "Ориентир по времени: 2-6 недель, с уточнением по ходу событий. "
        "Первые признаки сдвига обычно проявляются раньше - в пределах 7-10 дней."
    )
    timeframe = _sanitize_russian_text(payload.get("timeframe"), timeframe_fallback, min_words=5)
    result_fallback = _fallback_result_text(
        question,
        cards_data,
        is_health=is_health,
        is_binary_question=is_binary_question,
        need_partner_portrait=need_partner_portrait,
        need_place_hint=need_place_hint,
    )
    result = _sanitize_russian_text(payload.get("result"), result_fallback, min_words=8)
    portrait_personality_fallback = (
        "По линии личности считывается человек с внутренним стержнем и сдержанным темпераментом: "
        "сначала присматривается, затем проявляется уверенно и последовательно. "
        "В общении будет проявляться к тебе через конкретные действия и ответственность за слова."
    )
    portrait_appearance_fallback = (
        "По внешнему типажу вероятен аккуратный, собранный образ: ухоженный внешний вид, "
        "спокойная подача и уверенная манера держаться. "
        "Стиль скорее практичный, без лишней вычурности."
    )
    portrait_personality = _sanitize_russian_text(
        payload.get("portrait_personality"),
        portrait_personality_fallback,
        min_words=9,
    )
    portrait_appearance = _sanitize_russian_text(
        payload.get("portrait_appearance"),
        portrait_appearance_fallback,
        min_words=7,
    )
    place_hint_fallback = (
        "По энергетике места высокий шанс на живую точку контакта: пространство с движением людей, "
        "но без хаоса - уютная кофейня, камерное событие, творческая площадка, обучающий формат или "
        "место, где ты бываешь регулярно."
    )
    place_hint = _sanitize_russian_text(
        payload.get("place_hint"),
        place_hint_fallback,
        min_words=8,
    )
    extension_impact_fallback = _fallback_extension_impact(cards_data, added_cards_count)
    extension_impact = _sanitize_russian_text(
        payload.get("extension_impact"),
        extension_impact_fallback,
        min_words=10,
    )
    ui = PERSONA_UI.get(persona_key, PERSONA_UI["neutral"])
    parsed_questions = [item for item in question_items if str(item).strip()]
    if not parsed_questions:
        parsed_questions = [question]
    multi_mode = len(parsed_questions) > 1

    cards: list[str] = []
    for card in cards_data:
        card_name = _sanitize_russian_text(card.get("name"), "Карта без названия", min_words=1)
        position_ru = "перевернутая" if bool(card.get("is_reversed")) else "прямая"
        cards.append(f"{card_name} ({position_ru})")

    if len(cards) < cards_count:
        cards.extend(["Карта без описания"] * (cards_count - len(cards)))
    cards = cards[:cards_count]

    allow_infantile = persona_key == "supportive"

    if _has_weak_phrases(verdict, allow_infantile=allow_infantile):
        verdict = verdict_fallback
    if _has_weak_phrases(result, allow_infantile=allow_infantile):
        result = result_fallback
    if _has_weak_phrases(portrait_personality, allow_infantile=allow_infantile):
        portrait_personality = portrait_personality_fallback
    if _has_weak_phrases(portrait_appearance, allow_infantile=allow_infantile):
        portrait_appearance = portrait_appearance_fallback
    if _has_weak_phrases(place_hint, allow_infantile=allow_infantile):
        place_hint = place_hint_fallback
    if _has_weak_phrases(extension_impact, allow_infantile=allow_infantile):
        extension_impact = extension_impact_fallback

    if not multi_mode:
        analysis = _ensure_analysis_card_references(analysis, cards_data)

    verdict = _polish_tarot_russian(verdict)
    analysis = _polish_tarot_russian(analysis)
    result = _polish_tarot_russian(result)
    portrait_personality = _polish_tarot_russian(portrait_personality)
    portrait_appearance = _polish_tarot_russian(portrait_appearance)
    place_hint = _polish_tarot_russian(place_hint)
    extension_impact = _polish_tarot_russian(extension_impact)

    verdict = _soft_variate_text(verdict, chance=0.1)
    analysis = _soft_variate_text(analysis, chance=0.1)
    result = _soft_variate_text(result, chance=0.1)
    portrait_personality = _soft_variate_text(portrait_personality, chance=0.1)
    portrait_appearance = _soft_variate_text(portrait_appearance, chance=0.1)
    place_hint = _soft_variate_text(place_hint, chance=0.1)
    extension_impact = _soft_variate_text(extension_impact, chance=0.1)

    cards_text = "\n".join(f"• {_escape(card)}" for card in cards)
    timeframe_block = (
        "⏳ <b>Сроки:</b>\n"
        f"{_escape(timeframe)}\n\n"
        if need_timeframe
        else ""
    )
    portrait_block = (
        "🧠 <b>Портрет личности:</b>\n"
        f"{_escape(portrait_personality)}\n\n"
        "✨ <b>Внешний типаж:</b>\n"
        f"{_escape(portrait_appearance)}\n\n"
        if need_partner_portrait
        else ""
    )
    place_block = (
        "📍 <b>Вероятное место с сильной энергетикой:</b>\n"
        f"{_escape(place_hint)}\n\n"
        if need_place_hint
        else ""
    )
    extension_block = (
        "🧭 <b>Что изменил докид:</b>\n"
        f"{_escape(extension_impact)}\n\n"
        if extension_mode
        else ""
    )

    if multi_mode:
        answers_raw = payload.get("answers")
        answers_payload: list[dict[str, Any]] = []
        if isinstance(answers_raw, list):
            answers_payload = [item for item in answers_raw if isinstance(item, dict)]

        sections: list[str] = []
        segment = max(1, len(cards_data) // max(1, len(parsed_questions)))
        for idx, item_question in enumerate(parsed_questions, start=1):
            answer_payload = answers_payload[idx - 1] if idx - 1 < len(answers_payload) else {}
            item_is_health = _is_health_question(item_question)
            item_is_binary = _is_binary_question(item_question)
            item_need_portrait = _needs_partner_portrait(item_question)
            item_need_place = _needs_place_hint(item_question)
            start = (idx - 1) * segment
            focus_cards = cards_data[start : start + segment + 2] or cards_data

            item_verdict_fallback = _fallback_verdict_text(
                item_question,
                focus_cards,
                is_health=item_is_health,
                is_binary_question=item_is_binary,
                need_partner_portrait=item_need_portrait,
                need_place_hint=item_need_place,
            )
            item_result_fallback = _fallback_result_text(
                item_question,
                focus_cards,
                is_health=item_is_health,
                is_binary_question=item_is_binary,
                need_partner_portrait=item_need_portrait,
                need_place_hint=item_need_place,
            )
            item_analysis_fallback = _fallback_analysis_text(focus_cards)

            item_verdict = _sanitize_russian_text(
                answer_payload.get("verdict"),
                item_verdict_fallback,
                min_words=5,
            )
            item_verdict = _strip_forced_yes_no_prefix(
                item_verdict,
                item_verdict_fallback,
                item_is_binary,
            )
            if item_is_binary and not _is_direct_yes_no(item_verdict):
                item_verdict = item_verdict_fallback
            item_analysis = _sanitize_russian_text(
                answer_payload.get("analysis"),
                item_analysis_fallback,
                min_words=8,
            )
            item_result = _sanitize_russian_text(
                answer_payload.get("result"),
                item_result_fallback,
                min_words=6,
            )

            if _has_weak_phrases(item_verdict, allow_infantile=allow_infantile):
                item_verdict = item_verdict_fallback
            if _has_weak_phrases(item_result, allow_infantile=allow_infantile):
                item_result = item_result_fallback

            item_verdict = _polish_tarot_russian(item_verdict)
            item_analysis = _polish_tarot_russian(item_analysis)
            item_result = _polish_tarot_russian(item_result)

            item_verdict = _soft_variate_text(item_verdict, chance=0.1)
            item_analysis = _soft_variate_text(item_analysis, chance=0.1)
            item_result = _soft_variate_text(item_result, chance=0.1)

            sections.append(
                f"🧩 <b>Вопрос {idx}</b>\n"
                f"❓ {_escape(item_question)}\n"
                f"🎯 <b>Прямой ответ:</b> {_escape(item_verdict)}\n"
                f"💬 <b>Разбор по картам:</b> {_escape(item_analysis)}\n"
                f"✅ <b>Итог по вопросу:</b> {_escape(item_result)}"
            )

        multi_summary_fallback = (
            f"Разобрал {len(parsed_questions)} вопроса в одном раскладе: "
            "ниже по каждому вопросу отдельный прямой ответ и разбор."
        )
        verdict_multi = _sanitize_russian_text(payload.get("verdict"), multi_summary_fallback, min_words=6)
        if _has_weak_phrases(verdict_multi, allow_infantile=allow_infantile):
            verdict_multi = multi_summary_fallback
        verdict_multi = _polish_tarot_russian(verdict_multi)

        result_multi_fallback = (
            "Общий итог: по каждому вопросу есть отдельный ответ выше; "
            "ключевая линия складывается в последовательный сценарий без резких противоречий."
        )
        result_multi = _sanitize_russian_text(payload.get("result"), result_multi_fallback, min_words=6)
        if _has_weak_phrases(result_multi, allow_infantile=allow_infantile):
            result_multi = result_multi_fallback
        result_multi = _polish_tarot_russian(result_multi)

        multi_analysis = "\n\n".join(sections)
        return (
            "🃏 <b>Карты расклада:</b>\n"
            f"{cards_text}\n\n"
            "🎯 <b>Ключевой вывод:</b>\n"
            f"{_escape(verdict_multi)}\n\n"
            f"{timeframe_block}"
            "💫 <b>Глубокий анализ по вопросам:</b>\n"
            f"{multi_analysis}\n\n"
            "✅ <b>Итог:</b>\n"
            f"{_escape(result_multi)}"
        )

    return (
        "🃏 <b>Карты расклада:</b>\n"
        f"{cards_text}\n\n"
        "🎯 <b>Ключевой вывод:</b>\n"
        f"{_escape(verdict)}\n\n"
        f"{timeframe_block}"
        f"<b>{ui['analysis_title']}</b>\n"
        f"{_escape(analysis)}\n\n"
        f"{extension_block}"
        f"{portrait_block}"
        f"{place_block}"
        "✅ <b>Итог:</b>\n"
        f"{_escape(result)}"
    )


def _build_zodiac_html(sign1: str, sign2: str, payload: dict[str, Any]) -> str:
    love, passion, understanding = _zodiac_scores(sign1, sign2)
    energy = _relationship_energy_text(love, passion, understanding)

    analysis = _ensure_rich_text(
        payload.get("analysis"),
        "Главный фактор этой пары - зрелый диалог и уважение к разнице темпераментов.",
        min_words=8,
    )
    advice = _ensure_rich_text(
        payload.get("advice"),
        "Фиксируйте ожидания заранее и обсуждайте конфликт в день его появления.",
        min_words=5,
    )

    return (
        f"🌌 <b>Энергия пары:</b> {_escape(sign1)} + {_escape(sign2)}\n\n"
        "📊 <b>Совместимость:</b>\n"
        f"❤️ Любовь: {love}%\n"
        f"🔥 Страсть: {passion}%\n"
        f"🤝 Понимание: {understanding}%\n\n"
        "💞 <b>Характер союза:</b>\n"
        f"{_escape(energy)}\n\n"
        "🧭 <b>Как раскрыть отношения:</b>\n"
        f"{_escape(analysis)}\n\n"
        "💡 <b>Ключ к гармонии:</b>\n"
        f"{_escape(advice)}"
    )


def _build_daily_card_html(payload: dict[str, Any], card_name: str) -> str:
    title = _sanitize_russian_text(payload.get("title"), card_name, min_words=1)
    energy = _sanitize_russian_text(
        payload.get("energy"),
        "День требует спокойного ритма.",
        min_words=4,
    )
    action = _sanitize_russian_text(
        payload.get("action"),
        "Сделай одно важное дело и закрой его.",
        min_words=3,
    )

    return (
        f"🃏 <b>Карта дня:</b> {_escape(title)}\n\n"
        "✨ <b>Энергия дня:</b>\n"
        f"{_escape(energy)}\n\n"
        "🚀 <b>Действие дня:</b>\n"
        f"{_escape(action)}"
    )


def _dream_length_profile(length_setting: str) -> tuple[str, int]:
    if str(length_setting).strip().lower() == "long":
        return (
            "dream: 1-2 предложения, interpretation: 5-7 предложений, "
            "what_to_do: 3-4 предложения, summary: 2 предложения",
            620,
        )
    return (
        "dream: 1 предложение, interpretation: 3-4 предложения, "
        "what_to_do: 2-3 предложения, summary: 1-2 предложения",
        460,
    )


def _contains_tarot_terms(text: str) -> bool:
    normalized = str(text or "").lower().replace("ё", "е")
    markers = ("таро", "карт", "аркан", "колод")
    return any(marker in normalized for marker in markers)


def _dream_safe_text(value: Any, fallback: str, min_words: int) -> str:
    text = _sanitize_russian_text(value, fallback, min_words=min_words)
    if _contains_tarot_terms(text):
        return fallback
    return text


def _build_dream_html(payload: dict[str, Any], dream_text: str) -> str:
    dream_fallback = "Сон про эмоционально важную для тебя ситуацию, которую мозг сейчас активно обрабатывает."
    interpretation_fallback = (
        "Сон показывает внутреннее напряжение и попытку навести порядок в переживаниях. "
        "Повторяющиеся образы обычно связаны с темой контроля и безопасных границ. "
        "Это не предсказание, а сигнал о том, что психика хочет ясности и спокойного плана действий."
    )
    what_to_do_fallback = (
        "Зафиксируй ключевые детали сна в заметках, чтобы увидеть повторяющиеся триггеры. "
        "В течение дня выдели 20-30 минут на задачу, которую ты откладывал(а), чтобы снизить фоновую тревогу. "
        "Вечером перед сном убери экран за час и сделай короткую разгрузку головы."
    )
    summary_fallback = (
        "Итог: сон отражает твое текущее эмоциональное состояние и подсказывает навести порядок в приоритетах. "
        "Когда появится больше ясности в действиях, напряжение начнет снижаться."
    )

    dream = _dream_safe_text(payload.get("dream"), dream_fallback, min_words=5)
    interpretation = _dream_safe_text(
        payload.get("interpretation"),
        interpretation_fallback,
        min_words=12,
    )
    what_to_do = _dream_safe_text(payload.get("what_to_do"), what_to_do_fallback, min_words=10)
    summary = _dream_safe_text(payload.get("summary"), summary_fallback, min_words=8)

    if _contains_tarot_terms(dream_text):
        dream = dream_fallback

    return (
        "😴 <b>Сон:</b>\n"
        f"{_escape(dream)}\n\n"
        "🧠 <b>Трактовка сна:</b>\n"
        f"{_escape(interpretation)}\n\n"
        "🛠 <b>Что делать:</b>\n"
        f"{_escape(what_to_do)}\n\n"
        "✅ <b>Итог:</b>\n"
        f"{_escape(summary)}"
    )


def _cards_to_prompt_lines(cards_data: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, card in enumerate(cards_data, start=1):
        is_reversed = bool(card.get("is_reversed"))
        position = "reversed" if is_reversed else "upright"
        meaning = card.get("meaning_rev") if is_reversed else card.get("meaning_up")
        if not meaning:
            meaning = card.get("meaning_up", "")

        lines.append(
            f"{index}) {card.get('name', 'Неизвестная карта')}; "
            f"position={position}; meaning={meaning}"
        )
    return "\n".join(lines)


def _cards_coverage_rule(cards_count: int) -> str:
    if cards_count >= 18:
        return (
            "В analysis упомяни минимум 7 ключевых карт и разложи их по этапам: "
            "текущее состояние, скрытый фактор, точка разворота, ближайший результат."
        )
    if cards_count >= 6:
        return "В analysis упомяни минимум 3 ключевые карты и покажи их причинно-следственную связку."
    return "В analysis опирайся на ключевые карты без механического перечисления всей колоды."


def _adaptive_max_tokens(max_tokens: int) -> int:
    pending_now = int(_pending_requests)
    concurrency = max(1, int(config.AI_MAX_CONCURRENCY))

    if pending_now >= concurrency * 2:
        return max(220, int(max_tokens * 0.55))
    if pending_now >= concurrency:
        return max(240, int(max_tokens * 0.7))
    if pending_now >= max(4, concurrency // 2):
        return max(260, int(max_tokens * 0.82))
    return max_tokens


def _tarot_length_profile(
    length_setting: str,
    cards_count: int,
    need_timeframe: bool,
) -> tuple[str, int]:
    if length_setting == "long":
        timeframe_rule_size = ", timeframe: 1-3 предложения" if need_timeframe else ""
        if cards_count >= 18:
            length_rules = (
                "analysis: 10-14 предложений, "
                f"verdict: 2 предложения{timeframe_rule_size}, result: 2 предложения; "
                "без воды и повторов"
            )
            return length_rules, 980
        if cards_count >= 6:
            length_rules = (
                "analysis: 5-7 предложений, "
                f"verdict: 1-2 предложения{timeframe_rule_size}, result: 1-2 предложения; "
                "без воды и повторов"
            )
            return length_rules, 720
        if cards_count >= 3:
            length_rules = (
                "analysis: 4-6 предложений, "
                f"verdict: 1-2 предложения{timeframe_rule_size}, result: 1-2 предложения; "
                "без воды и повторов"
            )
            return length_rules, 620

        length_rules = (
            "analysis: 3-5 предложений, "
            f"verdict: 1-2 предложения{timeframe_rule_size}, result: 1-2 предложения; "
            "без воды и повторов"
        )
        return length_rules, 520

    timeframe_rule_size = ", timeframe: 1-2 предложения" if need_timeframe else ""
    if cards_count >= 18:
        length_rules = (
            "analysis: 8-11 предложений, "
            f"verdict: 1-2 предложения{timeframe_rule_size}, result: 2-3 предложения"
        )
        return length_rules, 860
    if cards_count >= 6:
        length_rules = (
            "analysis: 4-5 предложений, "
            f"verdict: 1-2 предложения{timeframe_rule_size}, result: 2 предложения"
        )
        return length_rules, 580
    if cards_count >= 3:
        length_rules = (
            "analysis: 3-4 предложения, "
            f"verdict: 1-2 предложения{timeframe_rule_size}, result: 1-2 предложения"
        )
        return length_rules, 500

    length_rules = (
        "analysis: 2-4 предложения, "
        f"verdict: 1-2 предложения{timeframe_rule_size}, result: 1-2 предложения"
    )
    return length_rules, 430


async def get_tarot_interpretation(
    question: str,
    cards_data: list[dict[str, Any]],
    persona_key: str = "neutral",
    length_setting: str = "short",
    extension_mode: bool = False,
    added_cards_count: int = 0,
) -> str:
    style = _persona_from_config(persona_key)
    question_items = _extract_question_items(question)
    if len(question_items) > 3:
        return (
            "❗ <b>На один расклад можно максимум 3 вопроса.</b>\n"
            "Сейчас вопросов больше. Выбери 1-3 самых важных и отправь заново."
        )

    if not question_items:
        question_items = [question]

    multi_mode = len(question_items) > 1
    primary_question = question_items[0]
    cards_count = len(cards_data)
    need_timeframe = any(_needs_timeframe(item) for item in question_items)
    is_health = any(_is_health_question(item) for item in question_items)
    is_binary_question = _is_binary_question(primary_question) if not multi_mode else False
    need_partner_portrait = (not multi_mode) and _needs_partner_portrait(primary_question)
    need_place_hint = (not multi_mode) and _needs_place_hint(primary_question)
    cache_key = _tarot_cache_key(
        question=question,
        cards_data=cards_data,
        persona_key=persona_key,
        length_setting=length_setting,
        extension_mode=extension_mode,
        added_cards_count=added_cards_count,
    )
    cached_response = _cache_get_tarot_response(cache_key)
    if cached_response:
        return cached_response

    length_rules, max_tokens = _tarot_length_profile(length_setting, cards_count, need_timeframe)
    token_cap = 1200 if extension_mode else 980
    if extension_mode:
        max_tokens = min(max_tokens + 220 + (max(1, int(added_cards_count)) * 40), token_cap)
    if need_partner_portrait:
        max_tokens = min(max_tokens + (160 if length_setting == "long" else 120), token_cap)
    if need_place_hint:
        max_tokens = min(max_tokens + 80, token_cap)
    max_tokens = _adaptive_max_tokens(max_tokens)
    coverage_rule = _cards_coverage_rule(cards_count)

    if persona_key == "supportive":
        persona_tone_rule = (
            "Пиши как живой практикующий таролог: естественно, грамотно и тепло. "
            "Допустимы мягкие милые формулировки и уменьшительно-ласкательные слова, "
            "но без перебора и с сохранением ясного смысла."
        )
    else:
        persona_tone_rule = (
            "Пиши как живой практикующий таролог: естественно, грамотно, без канцелярита и без детского тона. "
            "Запрещены уменьшительно-ласкательные слова и инфантильные метафоры "
            "(например, 'котенок', 'обнимашки')."
        )

    portrait_json_fields = (
        ", portrait_personality (string), portrait_appearance (string)"
        if need_partner_portrait
        else ""
    )
    place_json_fields = ", place_hint (string)" if need_place_hint else ""
    extension_json_fields = ", extension_impact (string)" if extension_mode else ""
    if multi_mode:
        json_fields = (
            "intro (string), cards (array[string]), verdict (string), "
            "answers (array[object{question (string), verdict (string), analysis (string), result (string)}]), "
            f"result (string){extension_json_fields}, timeframe (string)."
            if need_timeframe
            else "intro (string), cards (array[string]), verdict (string), "
            "answers (array[object{question (string), verdict (string), analysis (string), result (string)}]), "
            f"result (string){extension_json_fields}."
        )
    else:
        json_fields = (
            "intro (string), cards (array[string]), verdict (string), timeframe (string), analysis (string), "
            f"result (string){portrait_json_fields}{place_json_fields}{extension_json_fields}."
            if need_timeframe
            else "intro (string), cards (array[string]), verdict (string), analysis (string), "
            f"result (string){portrait_json_fields}{place_json_fields}{extension_json_fields}."
        )

    portrait_system_rule = (
        "Если PORTRAIT_REQUIRED=yes, обязательно заполни поля portrait_personality и portrait_appearance. "
        "Это вероятный таро-портрет, без категоричных фактов и без формулировок 'точно/гарантированно'. "
        "Опиши, как человек будет проявляться к спрашивающему, и дай общий внешний типаж без конкретных цифр."
        if need_partner_portrait
        else "Если PORTRAIT_REQUIRED=no, поля portrait_personality и portrait_appearance не добавляй."
    )
    place_system_rule = (
        "Если PLACE_REQUIRED=yes, обязательно заполни поле place_hint. "
        "Дай вероятную локацию по энергетике ситуации: тип места и обстановку, где выше шанс нужной встречи/события. "
        "Без точных адресов и без категоричных заявлений."
        if need_place_hint
        else "Если PLACE_REQUIRED=no, поле place_hint не добавляй."
    )
    multi_system_rule = (
        "Если QUESTIONS_COUNT > 1, обязательно заполни массив answers: по одному объекту на каждый вопрос из QUESTION_LIST "
        "в том же порядке. Не смешивай вопросы между собой и не пропускай элементы. "
        "Для каждого элемента с binary=yes начинай verdict прямо с 'Да:' или 'Нет:'."
        if multi_mode
        else "Если QUESTIONS_COUNT = 1, массив answers не добавляй."
    )
    extension_system_rule = (
        "Если EXTENSION_MODE=yes, обязательно заполни extension_impact: 3-5 предложений, "
        "что именно изменили докинутые карты и как это влияет на исход."
        if extension_mode
        else "Если EXTENSION_MODE=no, поле extension_impact не добавляй."
    )

    system_prompt = (
        f"ПЕРСОНА: {style['name']}\n"
        f"{style['prompt']}\n\n"
        "Стиль персоны должен быть заметно отличим от других персон.\n"
        "Ты отвечаешь только по таро-вопросам.\n"
        "Вопросы про физическое здоровье тоже считай таро-вопросами и отвечай по сути, без ухода от ответа.\n"
        "Если вопрос не относится к таро, верни JSON с коротким вежливым отказом.\n"
        "Используй только данные QUESTION и CARDS.\n"
        "Не придумывай карты, факты и события. Не ставь медицинские диагнозы и не назначай лечение.\n"
        "Не добавляй новые города, суммы, имена и детали, которых нет в вопросе или в картах.\n"
        "Не уходи от прямого ответа. Нельзя писать: 'карты не дают прямого ответа', 'я не могу ответить', "
        "или заменять ответ только советом обратиться к специалисту.\n"
        "Не обращайся к пользователю по имени и не придумывай имена.\n"
        "Избегай официального стиля с 'Вы/Вам'; используй дружелюбное 'ты'.\n"
        f"{persona_tone_rule}\n"
        "Соблюдай нормы русского языка: корректные формы слов, согласование и естественные формулировки.\n"
        "Не перекладывай ответственность на пользователя общими формулировками вроде 'все зависит от вас' "
        "или 'при условии, что...'.\n"
        "По вопросам здоровья сначала дай вероятностный исход по картам, затем действия.\n"
        "Ключевой вывод должен давать прямой ответ по сути вопроса уже в первых 1-2 предложениях.\n"
        "Если вопрос начинается с 'если ...', трактуй его как бинарный прогноз и отвечай прямо: 'Да:' или 'Нет:' с краткой причиной.\n"
        "Не используй формулировки 'скорее да', 'скорее нет' и 'ответ ближе к'. Для бинарного вопроса пиши прямо: 'Да:' или 'Нет:'.\n"
        "В analysis опирайся минимум на 2 карты и прямо связывай их с развитием ситуации.\n"
        f"{multi_system_rule}\n"
        f"{extension_system_rule}\n"
        f"{portrait_system_rule}\n"
        f"{place_system_rule}\n"
        "Допустимо 1-2 мягких таро-формулировки за ответ: 'проявится', 'по линии событий', 'по энергии ситуации'.\n"
        "verdict должен быть прямым и по сути вопроса. "
        "Смотри флаг BINARY_REQUIRED: если yes - дай формат 'Да/Нет' с короткой причиной; "
        "если no - дай краткий тезис без обязательного 'Да/Нет'.\n"
        "result должен быть финальным выводом без размытых оговорок.\n"
        "Строго соблюдай объем из RULES и не расширяй ответ сверх лимитов.\n"
        "Эмодзи используй умеренно: не более 1 эмодзи на абзац текста и ставь его в конце абзаца.\n"
        "Пиши только на грамотном русском языке (кириллица). Запрещены японские/китайские/корейские символы, "
        "ломаная транслитерация и мусорные символы.\n"
        "Формат ответа СТРОГО JSON-объект с ключами:\n"
        f"{json_fields}\n"
        "Никакого markdown, никаких комментариев вне JSON.\n"
        "Язык ответа: русский."
    )

    timeframe_rule = (
        "Обязательно укажи примерные сроки/даты: временное окно (например, 2-4 недели или конкретные даты), "
        "без категоричности, но с понятным ориентиром."
        if need_timeframe
        else "Сроки и даты не указывай вообще: их в этом ответе быть не должно."
    )

    extension_rule = (
        f"Это уточнение после докида {max(1, int(added_cards_count))} карт. "
        "В analysis и result явно опиши, что изменилось по сравнению с базовым раскладом: "
        "что усилилось, что ослабло и как это влияет на исход."
        if extension_mode
        else "Это основной расклад, без сравнения с предыдущим."
    )
    portrait_rule = (
        "Если PORTRAIT_REQUIRED=yes: portrait_personality = 2-4 предложения о характере и о том, "
        "как человек будет проявляться к тебе; portrait_appearance = 1-3 предложения о внешнем типаже "
        "и манере держаться."
        if need_partner_portrait
        else ""
    )
    place_rule = (
        "Если PLACE_REQUIRED=yes: place_hint = 2-4 предложения о вероятной локации и энергетике места, "
        "где шанс события выше."
        if need_place_hint
        else ""
    )
    multi_rule = (
        "Для каждого вопроса в answers дай: verdict (прямой ответ), analysis (конкретный разбор), "
        "result (краткий вывод по именно этому вопросу)."
        if multi_mode
        else ""
    )
    extension_rule_format = (
        "Если EXTENSION_MODE=yes: analysis должен быть заметно глубже базового ответа (минимум 5-8 предложений), "
        "а extension_impact - отдельным насыщенным блоком без повторов."
        if extension_mode
        else ""
    )

    question_list_lines = "\n".join(
        (
            f"{idx}. {item} "
            f"[binary={'yes' if _is_binary_question(item) else 'no'}; "
            f"timeframe={'yes' if _needs_timeframe(item) else 'no'}; "
            f"portrait={'yes' if _needs_partner_portrait(item) else 'no'}; "
            f"place={'yes' if _needs_place_hint(item) else 'no'}]"
        )
        for idx, item in enumerate(question_items, start=1)
    )

    user_prompt = (
        f"TODAY: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"QUESTION: {question}\n\n"
        f"QUESTIONS_COUNT: {len(question_items)}\n"
        f"QUESTION_LIST:\n{question_list_lines}\n\n"
        f"QUESTION_TYPE: {'health' if is_health else 'general'}\n"
        f"TIMEFRAME_REQUIRED: {'yes' if need_timeframe else 'no'}\n\n"
        f"BINARY_REQUIRED: {'yes' if is_binary_question else 'no'}\n\n"
        f"PORTRAIT_REQUIRED: {'yes' if need_partner_portrait else 'no'}\n\n"
        f"PLACE_REQUIRED: {'yes' if need_place_hint else 'no'}\n\n"
        f"EXTENSION_MODE: {'yes' if extension_mode else 'no'}\n"
        f"ADDED_CARDS: {max(0, int(added_cards_count))}\n\n"
        "CARDS:\n"
        f"{_cards_to_prompt_lines(cards_data)}\n\n"
        "RULES:\n"
        f"- cards array must have exactly {cards_count} elements\n"
        f"- {length_rules}\n"
        f"- {coverage_rule}\n"
        f"- {timeframe_rule}\n"
        f"- {extension_rule}"
        + (f"\n- {extension_rule_format}" if extension_rule_format else "")
        + (f"\n- {multi_rule}" if multi_rule else "")
        + (f"\n- {portrait_rule}" if portrait_rule else "")
        + (f"\n- {place_rule}" if place_rule else "")
    )

    try:
        payload = await _request_json_with_limits(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=style["temp"],
            max_tokens=max_tokens,
            max_attempts=2,
        )
        html_result = _build_tarot_html(
            payload,
            question=question,
            question_items=question_items,
            cards_count=cards_count,
            cards_data=cards_data,
            persona_key=persona_key,
            need_timeframe=need_timeframe,
            is_health=is_health,
            is_binary_question=is_binary_question,
            need_partner_portrait=need_partner_portrait,
            need_place_hint=need_place_hint,
            extension_mode=extension_mode,
            added_cards_count=added_cards_count,
        )
        _cache_put_tarot_response(cache_key, html_result)
        return html_result
    except ValueError as exc:
        logging.warning("Tarot JSON parse fallback triggered: %s", exc)
        html_result = _build_tarot_html(
            {},
            question=question,
            question_items=question_items,
            cards_count=cards_count,
            cards_data=cards_data,
            persona_key=persona_key,
            need_timeframe=need_timeframe,
            is_health=is_health,
            is_binary_question=is_binary_question,
            need_partner_portrait=need_partner_portrait,
            need_place_hint=need_place_hint,
            extension_mode=extension_mode,
            added_cards_count=added_cards_count,
        )
        _cache_put_tarot_response(cache_key, html_result)
        return html_result
    except AIOverloadedError:
        logging.warning("AI queue overloaded for tarot request")
        return (
            "⏳ <b>Сервис перегружен</b>\n"
            "Сейчас много запросов. Попробуйте снова через 1-2 минуты."
        )
    except Exception as exc:
        if "context_length_exceeded" in str(exc):
            return "🔮 <b>Поток энергии слишком мощный...</b>\nСлишком много карт. Попробуйте меньше."
        if isinstance(
            exc,
            (
                asyncio.TimeoutError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                APIError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ProxyError,
            ),
        ):
            logging.warning(
                "Tarot interpretation transient failure kind=%s: %s",
                _retry_error_kind(exc),
                exc,
            )
        else:
            logging.exception("Tarot interpretation generation failed")
        return "🔮 <b>Связь с космосом прервана...</b>\nПопробуйте еще раз через минуту."


async def get_zodiac_compatibility(sign1: str, sign2: str) -> str:
    love, passion, understanding = _zodiac_scores(sign1, sign2)

    system_prompt = (
        "Ты профессиональный астролог.\n"
        "Верни строго JSON-объект с ключами:\n"
        "analysis (string), advice (string).\n"
        "Текст должен быть живым и красивым, без канцелярита и без однословных фраз.\n"
        "Не используй пункты/списки, пиши цельными абзацами.\n"
        "Без markdown и без текста вне JSON. Язык: русский."
    )

    user_prompt = (
        f"Пара: {sign1} и {sign2}.\n"
        f"Оценки пары уже рассчитаны: любовь {love}%, страсть {passion}%, понимание {understanding}%.\n"
        "Сделай честный и практичный разбор.\n"
        "Ограничения: analysis 4-6 предложений, advice 1-2 предложения."
    )

    try:
        max_tokens = _adaptive_max_tokens(520)
        payload = await _request_json_with_limits(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.45,
            max_tokens=max_tokens,
            max_attempts=2,
        )
        return _build_zodiac_html(sign1, sign2, payload)
    except ValueError as exc:
        logging.warning("Zodiac JSON parse fallback triggered: %s", exc)
        return _build_zodiac_html(sign1, sign2, {})
    except AIOverloadedError:
        logging.warning("AI queue overloaded for zodiac request")
        return (
            "⏳ <b>Сервис перегружен</b>\n"
            "Сейчас много запросов. Попробуйте снова через 1-2 минуты."
        )
    except Exception as exc:
        if isinstance(
            exc,
            (
                asyncio.TimeoutError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                APIError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ProxyError,
            ),
        ):
            logging.warning(
                "Zodiac compatibility transient failure kind=%s: %s",
                _retry_error_kind(exc),
                exc,
            )
        else:
            logging.exception("Zodiac compatibility generation failed")
        return "🔮 <b>Звезды скрылись за тучами...</b>\nПопробуйте позже."


async def get_daily_card_prediction(card_name: str, card_meaning: str) -> str:
    daily_model = str(getattr(config, "AI_MODEL_DAILY", "") or "").strip()
    if not daily_model:
        daily_model = config.AI_MODEL
    fallback_model = str(config.AI_MODEL or "").strip()

    system_prompt = (
        "Ты мистический оракул.\n"
        "Верни строго JSON-объект с ключами:\n"
        "title (string), energy (string), action (string).\n"
        "Пиши только на грамотном русском языке (кириллица).\n"
        "Запрещены японские/китайские/корейские символы, ломаная транслитерация и мусорные символы.\n"
        "Без markdown и без текста вне JSON. Язык: русский."
    )

    user_prompt = (
        f"Карта: {card_name}. Значение: {card_meaning}.\n"
        "Ограничения: energy 2-4 предложения, action 1-2 предложения, "
        "конкретно и без мистической воды."
    )

    try:
        max_tokens = _adaptive_max_tokens(380)
        models_to_try: list[str] = [daily_model]
        if fallback_model and fallback_model not in models_to_try:
            models_to_try.append(fallback_model)

        for model_name in models_to_try:
            try:
                payload = await _request_json_with_limits(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.5,
                    max_tokens=max_tokens,
                    max_attempts=2,
                    model=model_name,
                )
                return _build_daily_card_html(payload, card_name)
            except Exception as exc:
                can_fallback = model_name != fallback_model and fallback_model
                if can_fallback and _is_model_not_found_error(exc):
                    logging.warning(
                        "Daily card model not found: %s; fallback to %s",
                        model_name,
                        fallback_model,
                    )
                    continue
                raise
    except ValueError as exc:
        logging.warning("Daily card JSON parse fallback triggered: %s", exc)
        return _build_daily_card_html({}, card_name)
    except AIOverloadedError:
        logging.warning("AI queue overloaded for daily card request")
        return (
            "⏳ <b>Сервис перегружен</b>\n"
            "Сейчас много запросов. Попробуйте снова через 1-2 минуты."
        )
    except Exception as exc:
        if isinstance(
            exc,
            (
                asyncio.TimeoutError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                APIError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ProxyError,
            ),
        ):
            logging.warning(
                "Daily card transient failure kind=%s: %s",
                _retry_error_kind(exc),
                exc,
            )
        else:
            logging.exception("Daily card prediction generation failed")
        return "🔮 <b>Эфир сегодня нестабилен...</b>\nПопробуйте позже."


async def get_dream_interpretation(
    dream_text: str,
    persona_key: str = "neutral",
    length_setting: str = "short",
) -> str:
    style = _persona_from_config(persona_key)
    length_rules, max_tokens = _dream_length_profile(length_setting)
    max_tokens = _adaptive_max_tokens(max_tokens)

    system_prompt = (
        f"ПЕРСОНА: {style['name']}\n"
        f"{style['prompt']}\n\n"
        "Ты аналитик снов.\n"
        "Задача: дать психологически безопасную, практичную и понятную трактовку сна.\n"
        "Запрещено упоминать таро, карты, арканы, колоды и гадание.\n"
        "Не ставь диагнозы и не назначай лечение.\n"
        "Не выдумывай фактов, которых нет в тексте сна.\n"
        "Пиши только на грамотном русском языке (кириллица).\n"
        "Формат ответа СТРОГО JSON-объект с ключами:\n"
        "dream (string), interpretation (string), what_to_do (string), summary (string).\n"
        "Без markdown и без текста вне JSON."
    )

    user_prompt = (
        f"СОН: {dream_text}\n\n"
        "Шаблон обязателен: сон -> трактовка сна -> что делать -> итог.\n"
        "Трактовка должна быть без мистики и без фатальных утверждений.\n"
        f"Ограничения по объему: {length_rules}."
    )

    try:
        payload = await _request_json_with_limits(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=max(0.1, min(1.0, float(style["temp"]))),
            max_tokens=max_tokens,
            max_attempts=2,
        )
        return _build_dream_html(payload, dream_text)
    except ValueError as exc:
        logging.warning("Dream JSON parse fallback triggered: %s", exc)
        return _build_dream_html({}, dream_text)
    except AIOverloadedError:
        logging.warning("AI queue overloaded for dream interpretation request")
        return (
            "⏳ <b>Сервис перегружен</b>\n"
            "Сейчас много запросов. Попробуйте снова через 1-2 минуты."
        )
    except Exception as exc:
        if isinstance(
            exc,
            (
                asyncio.TimeoutError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                APIError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ProxyError,
            ),
        ):
            logging.warning(
                "Dream interpretation transient failure kind=%s: %s",
                _retry_error_kind(exc),
                exc,
            )
        else:
            logging.exception("Dream interpretation generation failed")
        return "🔮 <b>Связь с сервисом прервалась...</b>\nПопробуйте еще раз через минуту."
