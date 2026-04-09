"""Tests para api_client.py — todo HTTP mockeado."""

from __future__ import annotations

import json
import urllib.error
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from claude_monitor import api_client
from claude_monitor.api_client import (
    get_cost_report,
    get_last_error,
    get_rate_limits,
    invalidate_key,
    reset_api_cache,
)


# --- Helpers ---


def _make_response(
    body: bytes = b"{}",
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Crea un mock de respuesta HTTP con headers."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status

    header_dict = headers or {}
    resp.headers = MagicMock()
    resp.headers.get = lambda key, default=None: header_dict.get(key, default)
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _rate_limit_headers(
    limit: int = 100000,
    remaining: int = 80000,
    reset_offset_secs: int = 45,
) -> dict[str, str]:
    reset = datetime.now(timezone.utc) + timedelta(seconds=reset_offset_secs)
    return {
        "anthropic-ratelimit-tokens-limit": str(limit),
        "anthropic-ratelimit-tokens-remaining": str(remaining),
        "anthropic-ratelimit-tokens-reset": reset.isoformat(),
        "anthropic-ratelimit-input-tokens-limit": str(limit // 2),
        "anthropic-ratelimit-input-tokens-remaining": str(remaining // 2),
        "anthropic-ratelimit-output-tokens-limit": str(limit // 2),
        "anthropic-ratelimit-output-tokens-remaining": str(remaining // 2),
    }


# --- Rate Limits ---


class TestGetRateLimits:
    def test_returns_empty_without_key(self):
        result = get_rate_limits("", ["claude-sonnet-4-6"])
        assert result == {}

    def test_returns_empty_without_models(self):
        result = get_rate_limits("sk-ant-api03-test", [])
        assert result == {}

    @patch("urllib.request.urlopen")
    def test_parses_headers_for_model(self, mock_urlopen):
        headers = _rate_limit_headers(limit=100000, remaining=60000)
        mock_urlopen.return_value = _make_response(
            body=b'{"input_tokens": 1}', headers=headers
        )

        result = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert "claude-sonnet-4-6" in result
        info = result["claude-sonnet-4-6"]
        assert info.model == "claude-sonnet-4-6"
        assert info.tokens_limit == 100000
        assert info.tokens_remaining == 60000
        assert info.usage_pct == pytest.approx(40.0)
        assert info.input_tokens_limit == 50000
        assert info.output_tokens_limit == 50000

    @patch("urllib.request.urlopen")
    def test_fetches_multiple_models(self, mock_urlopen):
        headers = _rate_limit_headers(limit=100000, remaining=80000)
        mock_urlopen.return_value = _make_response(headers=headers)

        models = ["claude-opus-4-6", "claude-sonnet-4-6"]
        result = get_rate_limits("sk-ant-api03-test", models)
        assert len(result) == 2
        assert "claude-opus-4-6" in result
        assert "claude-sonnet-4-6" in result
        assert result["claude-opus-4-6"].model == "claude-opus-4-6"
        assert result["claude-sonnet-4-6"].model == "claude-sonnet-4-6"
        assert mock_urlopen.call_count == 2

    @patch("urllib.request.urlopen")
    def test_returns_cached_on_second_call(self, mock_urlopen):
        headers = _rate_limit_headers()
        mock_urlopen.return_value = _make_response(headers=headers)

        r1 = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        r2 = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert r1["claude-sonnet-4-6"] is r2["claude-sonnet-4-6"]
        assert mock_urlopen.call_count == 1

    @patch("urllib.request.urlopen")
    def test_refetches_after_cache_expires(self, mock_urlopen):
        headers = _rate_limit_headers()
        mock_urlopen.return_value = _make_response(headers=headers)

        model = "claude-sonnet-4-6"
        get_rate_limits("sk-ant-api03-test", [model])
        assert mock_urlopen.call_count == 1

        # Forzar expiración del cache para este modelo
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        api_client._cached_rate_limits[model] = (
            api_client._cached_rate_limits[model][0],
            past,
        )

        mock_urlopen.return_value = _make_response(headers=headers)
        get_rate_limits("sk-ant-api03-test", [model])
        assert mock_urlopen.call_count == 2

    @patch("urllib.request.urlopen")
    def test_401_marks_key_invalid(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=BytesIO(b"")
        )

        result = get_rate_limits("sk-ant-api03-bad", ["claude-sonnet-4-6"])
        assert result == {}
        assert api_client._key_valid is False

    @patch("urllib.request.urlopen")
    def test_401_stops_fetching_remaining_models(self, mock_urlopen):
        """Después de un 401 en el primer modelo, no intenta el segundo."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=BytesIO(b"")
        )

        models = ["claude-opus-4-6", "claude-sonnet-4-6"]
        get_rate_limits("sk-ant-api03-bad", models)
        # Solo debe haber intentado 1 llamada (la primera falla con 401)
        assert mock_urlopen.call_count == 1

    @patch("urllib.request.urlopen")
    def test_429_does_not_mark_key_invalid(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=429, msg="Rate limited", hdrs=None, fp=BytesIO(b"")
        )

        result = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert result == {}
        assert api_client._key_valid is True

    @patch("urllib.request.urlopen")
    def test_network_error_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        result = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert result == {}

    @patch("urllib.request.urlopen")
    def test_missing_headers_returns_empty(self, mock_urlopen):
        mock_urlopen.return_value = _make_response(headers={})

        result = get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert result == {}

    @patch("urllib.request.urlopen")
    def test_invalid_key_skips_fetch(self, mock_urlopen):
        """Después de un 401, no vuelve a intentar."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=BytesIO(b"")
        )
        get_rate_limits("sk-ant-api03-bad", ["claude-sonnet-4-6"])

        mock_urlopen.reset_mock()
        get_rate_limits("sk-ant-api03-bad", ["claude-sonnet-4-6"])
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_partial_failure_keeps_successful_models(self, mock_urlopen):
        """Si un modelo falla pero otro ya estaba en cache, se retorna el cache."""
        headers = _rate_limit_headers()
        mock_urlopen.return_value = _make_response(headers=headers)

        # Fetch exitoso para sonnet
        get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert mock_urlopen.call_count == 1

        # Ahora opus falla, pero sonnet sigue en cache
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        result = get_rate_limits("sk-ant-api03-test", ["claude-opus-4-6", "claude-sonnet-4-6"])
        assert "claude-sonnet-4-6" in result
        assert "claude-opus-4-6" not in result


# --- Cost Report ---


class TestGetCostReport:
    def test_returns_none_without_key(self):
        assert get_cost_report("", date(2026, 4, 8)) is None

    @patch("urllib.request.urlopen")
    def test_parses_cost_data(self, mock_urlopen):
        body = json.dumps({
            "data": [
                {"cost_usd": "1.50"},
                {"cost_usd": "0.75"},
            ]
        }).encode()
        mock_urlopen.return_value = _make_response(body=body)

        report = get_cost_report("sk-ant-admin01-test", date(2026, 4, 8))
        assert report is not None
        assert report.total_cost_usd == pytest.approx(2.25)
        assert report.date == date(2026, 4, 8)

    @patch("urllib.request.urlopen")
    def test_empty_data_returns_zero_cost(self, mock_urlopen):
        body = json.dumps({"data": []}).encode()
        mock_urlopen.return_value = _make_response(body=body)

        report = get_cost_report("sk-ant-admin01-test", date(2026, 4, 8))
        assert report is not None
        assert report.total_cost_usd == 0.0

    @patch("urllib.request.urlopen")
    def test_cached_on_second_call(self, mock_urlopen):
        body = json.dumps({"data": [{"cost_usd": "1.00"}]}).encode()
        mock_urlopen.return_value = _make_response(body=body)

        get_cost_report("sk-ant-admin01-test", date(2026, 4, 8))
        get_cost_report("sk-ant-admin01-test", date(2026, 4, 8))
        assert mock_urlopen.call_count == 1

    @patch("urllib.request.urlopen")
    def test_401_marks_key_invalid(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=BytesIO(b"")
        )

        result = get_cost_report("sk-ant-admin01-bad", date(2026, 4, 8))
        assert result is None
        assert api_client._key_valid is False

    @patch("urllib.request.urlopen")
    def test_403_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=403, msg="", hdrs=None, fp=BytesIO(b"")
        )

        result = get_cost_report("sk-ant-api03-noadmin", date(2026, 4, 8))
        assert result is None

    @patch("urllib.request.urlopen")
    def test_malformed_json_returns_none(self, mock_urlopen):
        mock_urlopen.return_value = _make_response(body=b"not json")

        result = get_cost_report("sk-ant-admin01-test", date(2026, 4, 8))
        assert result is None


# --- Cache utilities ---


class TestCacheUtilities:
    @patch("urllib.request.urlopen")
    def test_reset_clears_everything(self, mock_urlopen):
        headers = _rate_limit_headers()
        mock_urlopen.return_value = _make_response(headers=headers)
        get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])

        reset_api_cache()
        assert api_client._cached_rate_limits == {}
        assert api_client._cached_cost_report is None
        assert api_client._key_valid is True

    @patch("urllib.request.urlopen")
    def test_invalidate_key_resets_validity(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=BytesIO(b"")
        )
        get_rate_limits("sk-ant-api03-bad", ["claude-sonnet-4-6"])
        assert api_client._key_valid is False

        invalidate_key()
        assert api_client._key_valid is True


# --- Error tracking ---


class TestErrorTracking:
    @patch("urllib.request.urlopen")
    def test_401_sets_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=BytesIO(b"")
        )
        get_rate_limits("sk-ant-api03-bad", ["claude-sonnet-4-6"])
        assert "invalid API key" in get_last_error()

    @patch("urllib.request.urlopen")
    def test_400_no_credits_sets_error(self, mock_urlopen):
        body = json.dumps({
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the Anthropic API.",
            },
        }).encode()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=400, msg="Bad Request", hdrs=None, fp=BytesIO(body)
        )
        get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        error = get_last_error()
        assert "no API credits" in error
        assert api_client._key_valid is False

    @patch("urllib.request.urlopen")
    def test_network_error_sets_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert "network error" in get_last_error()

    @patch("urllib.request.urlopen")
    def test_successful_call_clears_error(self, mock_urlopen):
        # Primero un error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        get_rate_limits("sk-ant-api03-test", ["claude-sonnet-4-6"])
        assert get_last_error() != ""

        # Reset y éxito
        reset_api_cache()
        assert get_last_error() == ""

    def test_reset_clears_error(self):
        api_client._last_error = "some error"
        reset_api_cache()
        assert get_last_error() == ""
