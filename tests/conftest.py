"""Fixtures compartidas para todos los tests."""

from pathlib import Path

import pytest

from claude_monitor.api_client import reset_api_cache
from claude_monitor.pricing_fetcher import reset_cache


@pytest.fixture(autouse=True)
def _isolate_pricing_cache(tmp_path, monkeypatch):
    """Redirige el cache de precios a un directorio temporal para aislar tests.

    Esto garantiza que los tests de log_parser (que llaman _calculate_cost →
    get_pricing_table) siempre usen los precios hardcoded de PRICING_TABLE,
    no un cache real en disco de ~/.claude-monitor/.
    """
    fake_cache = tmp_path / "pricing_cache.json"
    monkeypatch.setattr(
        "claude_monitor.pricing_fetcher.PRICING_CACHE_FILE", fake_cache
    )
    reset_cache()
    yield
    reset_cache()


@pytest.fixture(autouse=True)
def _isolate_api_cache():
    """Limpia el cache del api_client entre tests."""
    reset_api_cache()
    yield
    reset_api_cache()
