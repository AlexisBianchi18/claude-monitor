"""Tests para pricing_fetcher.py — sin llamadas de red."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_monitor.config import PRICING_TABLE, ModelPricing
from claude_monitor.pricing_fetcher import (
    MODEL_NAME_MAP,
    PRICING_CACHE_FILE,
    get_pricing_age,
    get_pricing_table,
    load_cached_pricing,
    parse_pricing_html,
    reset_cache,
    save_cached_pricing,
    should_fetch,
    update_pricing,
)

# --- Fixture HTML realista (estructura idéntica a la página real) ---

SAMPLE_PRICING_HTML = """\
<html><body>
<table class="w-full border-collapse">
<thead><tr>
<th>Model</th>
<th>Base Input Tokens</th>
<th>5m Cache Writes</th>
<th>1h Cache Writes</th>
<th>Cache Hits &amp; Refreshes</th>
<th>Output Tokens</th>
</tr></thead>
<tbody>
<tr><td>Claude Opus 4.6</td><td>$5 / MTok</td><td>$6.25 / MTok</td><td>$10 / MTok</td><td>$0.50 / MTok</td><td>$25 / MTok</td></tr>
<tr><td>Claude Opus 4.5</td><td>$5 / MTok</td><td>$6.25 / MTok</td><td>$10 / MTok</td><td>$0.50 / MTok</td><td>$25 / MTok</td></tr>
<tr><td>Claude Sonnet 4.6</td><td>$3 / MTok</td><td>$3.75 / MTok</td><td>$6 / MTok</td><td>$0.30 / MTok</td><td>$15 / MTok</td></tr>
<tr><td>Claude Haiku 4.5</td><td>$1 / MTok</td><td>$1.25 / MTok</td><td>$2 / MTok</td><td>$0.10 / MTok</td><td>$5 / MTok</td></tr>
<tr><td>Claude Haiku 3.5</td><td>$0.80 / MTok</td><td>$1 / MTok</td><td>$1.6 / MTok</td><td>$0.08 / MTok</td><td>$4 / MTok</td></tr>
</tbody>
</table>
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """Limpia cache en memoria antes y después de cada test."""
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    """Redirige el cache file a un directorio temporal."""
    cache_file = tmp_path / "pricing_cache.json"
    monkeypatch.setattr(
        "claude_monitor.pricing_fetcher.PRICING_CACHE_FILE", cache_file
    )
    return cache_file


# --- Parsing HTML ---


class TestParsePricingHtml:
    def test_parse_valid_table(self):
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        assert "claude-opus-4-6" in result
        assert "claude-sonnet-4-6" in result
        assert "claude-haiku-4-5-20251001" in result

    def test_opus_prices_correct(self):
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        opus = result["claude-opus-4-6"]
        assert opus.input == 5.0
        assert opus.output == 25.0
        assert opus.cache_read == 0.50
        assert opus.cache_create_5m == 6.25
        assert opus.cache_create_1h == 10.0

    def test_sonnet_prices_correct(self):
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        sonnet = result["claude-sonnet-4-6"]
        assert sonnet.input == 3.0
        assert sonnet.output == 15.0
        assert sonnet.cache_read == 0.30
        assert sonnet.cache_create_5m == 3.75
        assert sonnet.cache_create_1h == 6.0

    def test_haiku_prices_correct(self):
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        haiku = result["claude-haiku-4-5-20251001"]
        assert haiku.input == 1.0
        assert haiku.output == 5.0
        assert haiku.cache_read == 0.10
        assert haiku.cache_create_5m == 1.25
        assert haiku.cache_create_1h == 2.0

    def test_unmapped_models_skipped(self):
        """Claude Opus 4.5 y Haiku 3.5 no están en MODEL_NAME_MAP."""
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        # Solo los 3 modelos mapeados
        assert len(result) == 3

    def test_no_table_raises(self):
        with pytest.raises(ValueError, match="No se encontró"):
            parse_pricing_html("<html><body>No table here</body></html>")

    def test_missing_columns_raises(self):
        html = """
        <table><thead><tr>
        <th>Model</th><th>Base Input Tokens</th><th>Output Tokens</th>
        </tr></thead>
        <tbody><tr><td>Claude Opus 4.6</td><td>$5</td><td>$25</td></tr></tbody>
        </table>
        """
        with pytest.raises(ValueError, match="Columnas faltantes"):
            parse_pricing_html(html)

    def test_integer_and_decimal_prices_both_work(self):
        result = parse_pricing_html(SAMPLE_PRICING_HTML)
        # $5 (entero) y $0.50 (decimal) ambos parseados
        opus = result["claude-opus-4-6"]
        assert opus.input == 5.0
        assert opus.cache_read == 0.50


# --- Cache round-trip ---


class TestCacheRoundTrip:
    def test_save_and_load(self, cache_dir):
        pricing = {
            "claude-opus-4-6": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
        }
        save_cached_pricing(pricing)
        loaded, fetched_at = load_cached_pricing()
        assert loaded is not None
        assert fetched_at is not None
        assert "claude-opus-4-6" in loaded
        assert loaded["claude-opus-4-6"].input == 5.0
        assert loaded["claude-opus-4-6"].cache_create_1h == 10.0

    def test_missing_file_returns_none(self, cache_dir):
        loaded, fetched_at = load_cached_pricing()
        assert loaded is None
        assert fetched_at is None

    def test_corrupt_json_returns_none(self, cache_dir):
        cache_dir.write_text("not json{{{")
        loaded, fetched_at = load_cached_pricing()
        assert loaded is None
        assert fetched_at is None

    def test_invalid_structure_returns_none(self, cache_dir):
        cache_dir.write_text(json.dumps({"fetched_at": "bad", "models": "nope"}))
        loaded, fetched_at = load_cached_pricing()
        assert loaded is None
        assert fetched_at is None


# --- should_fetch ---


class TestShouldFetch:
    def test_no_cache_returns_true(self, cache_dir):
        assert should_fetch() is True

    def test_recent_cache_returns_false(self, cache_dir):
        data = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "models": {
                "claude-opus-4-6": {
                    "input": 5.0, "output": 25.0, "cache_read": 0.5,
                    "cache_create_5m": 6.25, "cache_create_1h": 10.0,
                },
            },
        }
        cache_dir.write_text(json.dumps(data))
        assert should_fetch() is False

    def test_old_cache_returns_true(self, cache_dir):
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        data = {
            "fetched_at": old_time.isoformat(),
            "models": {
                "claude-opus-4-6": {
                    "input": 5.0, "output": 25.0, "cache_read": 0.5,
                    "cache_create_5m": 6.25, "cache_create_1h": 10.0,
                },
            },
        }
        cache_dir.write_text(json.dumps(data))
        assert should_fetch() is True


# --- get_pricing_table ---


class TestGetPricingTable:
    def test_returns_hardcoded_when_no_cache(self, cache_dir):
        result = get_pricing_table()
        assert result is PRICING_TABLE

    def test_returns_cached_when_available(self, cache_dir):
        pricing = {"claude-opus-4-6": ModelPricing(99.0, 99.0, 99.0, 99.0, 99.0)}
        save_cached_pricing(pricing)
        result = get_pricing_table()
        assert result["claude-opus-4-6"].input == 99.0

    def test_memory_cache_avoids_disk_reads(self, cache_dir):
        pricing = {"claude-opus-4-6": ModelPricing(42.0, 42.0, 42.0, 42.0, 42.0)}
        save_cached_pricing(pricing)
        # Primera llamada lee del disco
        get_pricing_table()
        # Borramos el archivo
        cache_dir.unlink()
        # Segunda llamada usa memoria
        result = get_pricing_table()
        assert result["claude-opus-4-6"].input == 42.0


# --- update_pricing ---


class TestUpdatePricing:
    def test_success(self, cache_dir):
        with patch(
            "claude_monitor.pricing_fetcher.fetch_pricing_page",
            return_value=SAMPLE_PRICING_HTML,
        ):
            pricing, error = update_pricing()
            assert error is None
            assert "claude-opus-4-6" in pricing
            assert cache_dir.exists()

    def test_network_error_returns_fallback(self, cache_dir):
        with patch(
            "claude_monitor.pricing_fetcher.fetch_pricing_page",
            side_effect=OSError("Connection refused"),
        ):
            pricing, error = update_pricing()
            assert error is not None
            assert "Connection refused" in error
            # Debe retornar fallback (hardcoded)
            assert pricing is PRICING_TABLE

    def test_parse_error_returns_fallback(self, cache_dir):
        with patch(
            "claude_monitor.pricing_fetcher.fetch_pricing_page",
            return_value="<html>no table</html>",
        ):
            pricing, error = update_pricing()
            assert error is not None
            assert pricing is PRICING_TABLE


# --- MODEL_NAME_MAP consistency ---


class TestModelNameMap:
    def test_all_mapped_ids_exist_in_hardcoded_defaults(self):
        for display_name, model_id in MODEL_NAME_MAP.items():
            assert model_id in PRICING_TABLE, (
                f"{display_name} maps to {model_id} which is not in PRICING_TABLE"
            )


# --- get_pricing_age ---


class TestGetPricingAge:
    def test_returns_none_when_no_cache(self, cache_dir):
        assert get_pricing_age() is None

    def test_returns_today_for_recent(self, cache_dir):
        pricing = {"claude-opus-4-6": ModelPricing(5.0, 25.0, 0.5, 6.25, 10.0)}
        save_cached_pricing(pricing)
        age_str = get_pricing_age()
        assert age_str == "updated today"

    def test_returns_days_for_old_cache(self, cache_dir):
        old_time = datetime.now(timezone.utc) - timedelta(days=3)
        data = {
            "fetched_at": old_time.isoformat(),
            "models": {
                "claude-opus-4-6": {
                    "input": 5.0, "output": 25.0, "cache_read": 0.5,
                    "cache_create_5m": 6.25, "cache_create_1h": 10.0,
                },
            },
        }
        cache_dir.write_text(json.dumps(data))
        age_str = get_pricing_age()
        assert "3d ago" in age_str
