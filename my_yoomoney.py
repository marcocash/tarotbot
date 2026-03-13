import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx

import config


_YOOMONEY_HISTORY_URL = "https://yoomoney.ru/api/operation-history"
_yoomoney_unavailable_until = 0.0


def _timeout() -> httpx.Timeout:
    connect_timeout = max(2.0, float(config.YOOMONEY_CHECK_CONNECT_TIMEOUT_SEC))
    read_timeout = max(connect_timeout, float(config.YOOMONEY_CHECK_READ_TIMEOUT_SEC))
    return httpx.Timeout(connect=connect_timeout, read=read_timeout, write=10.0, pool=10.0)


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ProxyError,
        ),
    ):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}

    return False


def _is_in_cooldown() -> bool:
    return time.monotonic() < _yoomoney_unavailable_until


def _set_cooldown() -> None:
    global _yoomoney_unavailable_until
    cooldown_sec = max(3.0, float(config.YOOMONEY_CHECK_COOLDOWN_SEC))
    _yoomoney_unavailable_until = time.monotonic() + cooldown_sec


def _check_payment_once(target_label: str) -> bool:
    headers = {
        "Authorization": f"Bearer {config.YOOMONEY_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "label": target_label,
        "records": "10",
    }

    with httpx.Client(
        headers=headers,
        timeout=_timeout(),
        trust_env=bool(config.YOOMONEY_HTTP_TRUST_ENV),
    ) as client:
        response = client.post(_YOOMONEY_HISTORY_URL, data=data)
        response.raise_for_status()
        payload = response.json()

    api_error = str(payload.get("error") or "").strip()
    if api_error:
        if api_error in {"illegal_param_label", "illegal_params"}:
            return False

        logging.error("YoMoney API error while checking payment: %s", api_error)
        return False

    operations = payload.get("operations")
    if not isinstance(operations, list):
        return False

    for operation in operations:
        if not isinstance(operation, dict):
            continue

        if str(operation.get("label") or "") != target_label:
            continue

        if str(operation.get("status") or "").lower() == "success":
            return True

    return False


def create_pay_link(amount: int, label: str, description: str) -> str:
    base_url = "https://yoomoney.ru/quickpay/confirm.xml"
    params = {
        "receiver": config.YOOMONEY_WALLET,
        "quickpay-form": "shop",
        "targets": description,
        "paymentType": "AC",
        "sum": str(amount),
        "label": label,
    }
    return f"{base_url}?{urlencode(params)}"


def _check_payment_sync(target_label: str) -> bool:
    if _is_in_cooldown():
        return False

    retries = max(1, int(config.YOOMONEY_CHECK_RETRIES))
    backoff = max(0.2, float(config.YOOMONEY_CHECK_RETRY_BACKOFF_SEC))

    try:
        for attempt in range(1, retries + 1):
            try:
                return _check_payment_once(target_label)
            except Exception as exc:
                if attempt >= retries or not _is_retryable_http_error(exc):
                    if _is_retryable_http_error(exc):
                        _set_cooldown()
                        logging.warning(
                            "YoMoney check temporary network error (attempt %s/%s): %s",
                            attempt,
                            retries,
                            exc,
                        )
                    else:
                        logging.exception("YoMoney payment check failed")
                    return False

                sleep_for = min(backoff * (2 ** (attempt - 1)), 5.0)
                time.sleep(sleep_for)

        return False
    except Exception:
        logging.exception("YoMoney payment check failed unexpectedly")
        return False


async def check_payment(target_label: str) -> bool:
    return await asyncio.to_thread(_check_payment_sync, target_label)
