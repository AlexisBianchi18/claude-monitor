"""Cliente para la API de Anthropic: rate limits y cost report."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .models import ApiCostReport, RateLimitInfo

logger = logging.getLogger(__name__)

API_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
API_TIMEOUT_SECONDS = 10

# Intervalos de polling (segundos)
RATE_LIMIT_POLL_SECONDS = 60
COST_REPORT_POLL_SECONDS = 300

# --- Cache de módulo ---

# Cache per-model: {model_id: (RateLimitInfo, fetched_at)}
_cached_rate_limits: dict[str, tuple[RateLimitInfo, datetime]] = {}
_cached_cost_report: ApiCostReport | None = None
_cost_report_fetched_at: datetime | None = None
_key_valid: bool = True
_last_error: str = ""


def _is_cache_fresh(fetched_at: datetime | None, max_age_seconds: int) -> bool:
    if fetched_at is None:
        return False
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age < max_age_seconds


def _api_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }


# --- Error tracking ---


def _set_last_error(msg: str) -> None:
    global _last_error  # noqa: PLW0603
    _last_error = msg
    logger.warning("API error: %s", msg)


def _set_error_from_http(exc: urllib.error.HTTPError) -> None:
    """Extrae un mensaje legible de un HTTPError y actualiza estado."""
    global _key_valid  # noqa: PLW0603

    # Intentar leer el mensaje del body JSON
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        detail = body.get("error", {}).get("message", "")
    except Exception:
        pass

    if exc.code == 401:
        _key_valid = False
        _set_last_error("invalid API key (401)")
    elif exc.code == 400 and "credit balance" in detail.lower():
        _key_valid = False
        _set_last_error("no API credits — add credits at console.anthropic.com")
    elif exc.code == 429:
        _set_last_error("rate limited (429), using cached data")
    else:
        msg = f"HTTP {exc.code}"
        if detail:
            msg += f": {detail}"
        _set_last_error(msg)


def get_last_error() -> str:
    """Retorna el último error de la API, o cadena vacía si no hay."""
    return _last_error


# --- Rate Limits ---


def _fetch_rate_limits_for_model(
    api_key: str, model: str
) -> RateLimitInfo | None:
    """Hace POST a count_tokens para un modelo y parsea los headers de rate limit."""
    global _key_valid  # noqa: PLW0603

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "x"}],
    }).encode()

    req = urllib.request.Request(
        f"{API_BASE}/v1/messages/count_tokens",
        data=body,
        headers=_api_headers(api_key),
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS)
        headers = resp.headers

        tokens_limit = int(headers.get("anthropic-ratelimit-tokens-limit", "0"))
        tokens_remaining = int(
            headers.get("anthropic-ratelimit-tokens-remaining", "0")
        )
        tokens_reset_str = headers.get("anthropic-ratelimit-tokens-reset", "")

        if not tokens_limit or not tokens_reset_str:
            return None

        tokens_reset = datetime.fromisoformat(tokens_reset_str)

        return RateLimitInfo(
            model=model,
            tokens_limit=tokens_limit,
            tokens_remaining=tokens_remaining,
            tokens_reset=tokens_reset,
            input_tokens_limit=int(
                headers.get("anthropic-ratelimit-input-tokens-limit", "0")
            ),
            input_tokens_remaining=int(
                headers.get("anthropic-ratelimit-input-tokens-remaining", "0")
            ),
            output_tokens_limit=int(
                headers.get("anthropic-ratelimit-output-tokens-limit", "0")
            ),
            output_tokens_remaining=int(
                headers.get("anthropic-ratelimit-output-tokens-remaining", "0")
            ),
        )
    except urllib.error.HTTPError as exc:
        _set_error_from_http(exc)
        return None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _set_last_error(f"network error: {exc}")
        return None


def get_rate_limits(
    api_key: str, models: list[str] | None = None
) -> dict[str, RateLimitInfo]:
    """Retorna rate limits por modelo (desde cache si es fresco, si no hace fetch).

    Args:
        api_key: API key de Anthropic.
        models: Lista de model IDs a consultar. Si es None o vacía, retorna cache.

    Returns:
        Dict de model_id → RateLimitInfo para cada modelo consultado.
    """
    global _cached_rate_limits  # noqa: PLW0603

    if not api_key or not _key_valid:
        return {m: info for m, (info, _) in _cached_rate_limits.items()}

    if not models:
        return {m: info for m, (info, _) in _cached_rate_limits.items()}

    for model in models:
        cached = _cached_rate_limits.get(model)
        if cached and _is_cache_fresh(cached[1], RATE_LIMIT_POLL_SECONDS):
            continue  # cache fresco, no re-fetch

        result = _fetch_rate_limits_for_model(api_key, model)
        if result is not None:
            _cached_rate_limits[model] = (result, datetime.now(timezone.utc))
        if not _key_valid:
            break  # 401 — no seguir intentando

    return {m: info for m, (info, _) in _cached_rate_limits.items()}


# --- Cost Report (Admin API) ---


def _fetch_cost_report(api_key: str, target_date: date) -> ApiCostReport | None:
    """GET /v1/organizations/cost_report para obtener costos reales."""
    global _key_valid  # noqa: PLW0603

    starting_at = f"{target_date.isoformat()}T00:00:00Z"
    next_day = target_date + timedelta(days=1)
    ending_at = f"{next_day.isoformat()}T00:00:00Z"

    url = (
        f"{API_BASE}/v1/organizations/cost_report"
        f"?starting_at={starting_at}&ending_at={ending_at}&bucket_width=1d"
    )

    req = urllib.request.Request(
        url,
        headers=_api_headers(api_key),
        method="GET",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS)
        data = json.loads(resp.read().decode("utf-8"))

        total_cost = 0.0
        for bucket in data.get("data", []):
            cost_str = bucket.get("cost_usd", "0")
            total_cost += float(cost_str)

        return ApiCostReport(date=target_date, total_cost_usd=total_cost)
    except urllib.error.HTTPError as exc:
        _set_error_from_http(exc)
        return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        _set_last_error(f"network error: {exc}")
        return None


def get_cost_report(api_key: str, target_date: date) -> ApiCostReport | None:
    """Retorna cost report (desde cache si es fresco, si no hace fetch)."""
    global _cached_cost_report, _cost_report_fetched_at  # noqa: PLW0603

    if not api_key or not _key_valid:
        return _cached_cost_report

    if _is_cache_fresh(_cost_report_fetched_at, COST_REPORT_POLL_SECONDS):
        return _cached_cost_report

    result = _fetch_cost_report(api_key, target_date)
    if result is not None:
        _cached_cost_report = result
        _cost_report_fetched_at = datetime.now(timezone.utc)
    return _cached_cost_report


# --- Utilidades ---


def reset_api_cache() -> None:
    """Limpia todo el cache (útil para tests)."""
    global _cached_rate_limits  # noqa: PLW0603
    global _cached_cost_report, _cost_report_fetched_at  # noqa: PLW0603
    global _key_valid, _last_error  # noqa: PLW0603
    _cached_rate_limits = {}
    _cached_cost_report = None
    _cost_report_fetched_at = None
    _key_valid = True
    _last_error = ""


def invalidate_key() -> None:
    """Resetea el estado de validez de la key (cuando el usuario la cambia)."""
    global _key_valid  # noqa: PLW0603
    _key_valid = True
    reset_api_cache()
