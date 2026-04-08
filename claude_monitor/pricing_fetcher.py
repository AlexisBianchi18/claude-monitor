"""Fetcher y cache de precios desde la página oficial de Anthropic."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .config import CONFIG_DIR, PRICING_TABLE, ModelPricing

logger = logging.getLogger(__name__)

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_CACHE_FILE = CONFIG_DIR / "pricing_cache.json"
FETCH_INTERVAL_HOURS = 24
FETCH_TIMEOUT_SECONDS = 10

# Mapeo de nombres en la web a model IDs usados en los logs.
# Se ignoran modelos no listados aquí (legacy, deprecated, etc.).
MODEL_NAME_MAP: dict[str, str] = {
    "Claude Opus 4.6": "claude-opus-4-6",
    "Claude Sonnet 4.6": "claude-sonnet-4-6",
    "Claude Haiku 4.5": "claude-haiku-4-5-20251001",
}

# Mapeo de nombres de columna del header a campos de ModelPricing
_COLUMN_MAP: dict[str, str] = {
    "Base Input Tokens": "input",
    "Output Tokens": "output",
    "Cache Hits & Refreshes": "cache_read",
    "Cache Hits &amp; Refreshes": "cache_read",
    "5m Cache Writes": "cache_create_5m",
    "1h Cache Writes": "cache_create_1h",
}

# Variable de módulo para evitar lecturas repetidas de disco.
_cached_pricing: dict[str, ModelPricing] | None = None
_cached_fetched_at: datetime | None = None

_PRICE_RE = re.compile(r"\$([\d.]+)")


# --- HTML parsing ---


class _PricingTableParser(HTMLParser):
    """Extrae celdas de la primera tabla HTML cuyo header contiene 'Base Input Tokens'."""

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._found_target = False
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self.rows: list[list[str]] = []
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "table":
            self._in_table = True
            self._found_target = False
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in ("th", "td"):
            self._in_cell = True
            self._current_cell = ""

    def handle_endtag(self, tag: str) -> None:
        if self._done:
            return
        if tag in ("th", "td") and self._in_cell:
            self._in_cell = False
            self._current_row.append(self._current_cell.strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row:
                # Detectar si esta es la tabla de precios
                if not self._found_target and "Base Input Tokens" in self._current_row:
                    self._found_target = True
                if self._found_target:
                    self.rows.append(self._current_row)
        elif tag == "table" and self._in_table:
            if self._found_target:
                self._done = True
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell += data

    def handle_entityref(self, name: str) -> None:
        if self._in_cell:
            self._current_cell += f"&{name};"


def parse_pricing_html(html: str) -> dict[str, ModelPricing]:
    """Parsea el HTML de la página de pricing y retorna un dict de precios."""
    parser = _PricingTableParser()
    parser.feed(html)

    if not parser.rows:
        raise ValueError("No se encontró la tabla de precios en el HTML")

    header = parser.rows[0]
    # Mapear índice de columna → campo de ModelPricing
    col_indices: dict[str, int] = {}
    for i, col_name in enumerate(header):
        field = _COLUMN_MAP.get(col_name)
        if field:
            col_indices[field] = i

    required = {"input", "output", "cache_read", "cache_create_5m", "cache_create_1h"}
    if not required.issubset(col_indices.keys()):
        missing = required - col_indices.keys()
        raise ValueError(f"Columnas faltantes en la tabla: {missing}")

    result: dict[str, ModelPricing] = {}
    for row in parser.rows[1:]:
        if len(row) < len(header):
            continue
        model_display = row[0].strip()
        model_id = MODEL_NAME_MAP.get(model_display)
        if model_id is None:
            continue

        prices: dict[str, float] = {}
        try:
            for field, idx in col_indices.items():
                m = _PRICE_RE.search(row[idx])
                if m is None:
                    raise ValueError(f"No price in '{row[idx]}'")
                prices[field] = float(m.group(1))
        except (ValueError, IndexError):
            logger.warning("No se pudo parsear precios para %s", model_display)
            continue

        result[model_id] = ModelPricing(
            input=prices["input"],
            output=prices["output"],
            cache_read=prices["cache_read"],
            cache_create_5m=prices["cache_create_5m"],
            cache_create_1h=prices["cache_create_1h"],
        )

    if not result:
        raise ValueError("No se encontraron modelos conocidos en la tabla de precios")

    return result


# --- Cache ---


def load_cached_pricing() -> tuple[dict[str, ModelPricing] | None, datetime | None]:
    """Lee pricing_cache.json. Retorna (None, None) si no existe o está corrupto."""
    try:
        raw = PRICING_CACHE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, None

        fetched_at = datetime.fromisoformat(data["fetched_at"])
        models_raw = data["models"]
        pricing: dict[str, ModelPricing] = {}
        for model_id, vals in models_raw.items():
            pricing[model_id] = ModelPricing(
                input=vals["input"],
                output=vals["output"],
                cache_read=vals["cache_read"],
                cache_create_5m=vals["cache_create_5m"],
                cache_create_1h=vals["cache_create_1h"],
            )
        return pricing, fetched_at
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None, None


def save_cached_pricing(pricing: dict[str, ModelPricing]) -> None:
    """Guarda precios en pricing_cache.json con timestamp."""
    data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            model_id: {
                "input": p.input,
                "output": p.output,
                "cache_read": p.cache_read,
                "cache_create_5m": p.cache_create_5m,
                "cache_create_1h": p.cache_create_1h,
            }
            for model_id, p in pricing.items()
        },
    }
    PRICING_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRICING_CACHE_FILE.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


# --- API pública ---


def should_fetch() -> bool:
    """True si no hay cache o tiene más de FETCH_INTERVAL_HOURS horas."""
    _, fetched_at = load_cached_pricing()
    if fetched_at is None:
        return True
    age = datetime.now(timezone.utc) - fetched_at
    return age.total_seconds() > FETCH_INTERVAL_HOURS * 3600


def fetch_pricing_page() -> str:
    """Descarga el HTML de la página de precios de Anthropic."""
    req = urllib.request.Request(
        PRICING_URL,
        headers={"User-Agent": "claude-monitor/1.0"},
    )
    resp = urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS)
    return resp.read().decode("utf-8")


def update_pricing() -> tuple[dict[str, ModelPricing], str | None]:
    """Fetch → parse → save. Retorna (pricing, error_msg).

    En caso de error retorna los precios del fallback y un mensaje de error.
    """
    global _cached_pricing, _cached_fetched_at  # noqa: PLW0603

    try:
        html = fetch_pricing_page()
        pricing = parse_pricing_html(html)
        save_cached_pricing(pricing)
        _cached_pricing = pricing
        _cached_fetched_at = datetime.now(timezone.utc)
        return pricing, None
    except Exception as exc:
        logger.warning("Error actualizando precios: %s", exc)
        return get_pricing_table(), str(exc)


def get_pricing_table() -> dict[str, ModelPricing]:
    """Retorna la tabla de precios activa: cache en memoria > disco > hardcoded."""
    global _cached_pricing, _cached_fetched_at  # noqa: PLW0603

    if _cached_pricing is not None:
        return _cached_pricing

    pricing, fetched_at = load_cached_pricing()
    if pricing is not None:
        _cached_pricing = pricing
        _cached_fetched_at = fetched_at
        return pricing

    return PRICING_TABLE


def get_pricing_age() -> str | None:
    """Retorna texto legible sobre la antigüedad de los precios, o None si usa defaults."""
    global _cached_fetched_at  # noqa: PLW0603

    if _cached_fetched_at is None:
        _, fetched_at = load_cached_pricing()
        if fetched_at is None:
            return None
        _cached_fetched_at = fetched_at

    age = datetime.now(timezone.utc) - _cached_fetched_at
    if age.days == 0:
        return "updated today"
    if age.days == 1:
        return "updated yesterday"
    return f"updated {age.days}d ago"


def reset_cache() -> None:
    """Limpia la variable de módulo (útil para tests)."""
    global _cached_pricing, _cached_fetched_at  # noqa: PLW0603
    _cached_pricing = None
    _cached_fetched_at = None
