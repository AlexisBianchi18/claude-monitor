"""Tests para ConfigManager — configuración persistente."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from claude_monitor.config import (
    COST_ALERT_THRESHOLD_USD,
    MAX_PROJECTS_IN_MENU,
    REFRESH_INTERVAL_SECONDS,
    ConfigManager,
)


@pytest.fixture()
def config_path(tmp_path):
    """Retorna un path temporal para el archivo de config."""
    return tmp_path / "config.json"


# --- Creación y defaults ---


class TestDefaults:
    def test_creates_with_defaults_when_no_file(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == REFRESH_INTERVAL_SECONDS
        assert mgr.alert_threshold == COST_ALERT_THRESHOLD_USD
        assert mgr.max_projects == MAX_PROJECTS_IN_MENU

    def test_save_creates_directory_and_file(self, tmp_path):
        nested = tmp_path / "subdir" / "config.json"
        mgr = ConfigManager(config_path=nested)
        mgr.save()
        assert nested.is_file()
        data = json.loads(nested.read_text())
        assert data["refresh_interval_seconds"] == REFRESH_INTERVAL_SECONDS

    def test_load_existing_file(self, config_path):
        config_path.write_text(json.dumps({
            "refresh_interval_seconds": 60,
            "cost_alert_threshold_usd": 10.0,
            "max_projects_in_menu": 5,
        }))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == 60
        assert mgr.alert_threshold == 10.0
        assert mgr.max_projects == 5


# --- JSON corrupto ---


class TestCorruptedConfig:
    def test_corrupted_json_uses_defaults(self, config_path):
        config_path.write_text("this is not json{{{")
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == REFRESH_INTERVAL_SECONDS
        assert mgr.alert_threshold == COST_ALERT_THRESHOLD_USD

    def test_json_array_instead_of_object_uses_defaults(self, config_path):
        config_path.write_text("[1, 2, 3]")
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == REFRESH_INTERVAL_SECONDS

    def test_empty_file_uses_defaults(self, config_path):
        config_path.write_text("")
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == REFRESH_INTERVAL_SECONDS


# --- Merge con defaults ---


class TestMergeWithDefaults:
    def test_missing_keys_filled_from_defaults(self, config_path):
        config_path.write_text(json.dumps({
            "refresh_interval_seconds": 120,
        }))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.refresh_interval == 120
        assert mgr.alert_threshold == COST_ALERT_THRESHOLD_USD
        assert mgr.max_projects == MAX_PROJECTS_IN_MENU

    def test_extra_keys_preserved(self, config_path):
        config_path.write_text(json.dumps({
            "custom_key": "preserved",
        }))
        mgr = ConfigManager(config_path=config_path)
        mgr.save()
        data = json.loads(config_path.read_text())
        assert data["custom_key"] == "preserved"


# --- Daily offset ---


class TestDailyOffset:
    def test_no_offset_returns_zero(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.get_daily_offset(date(2026, 4, 8)) == 0.0

    def test_set_and_get_offset(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_daily_offset(date(2026, 4, 8), 12.50)
        assert mgr.get_daily_offset(date(2026, 4, 8)) == 12.50

    def test_offset_persists_to_disk(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_daily_offset(date(2026, 4, 8), 7.25)

        # Recargar desde disco
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.get_daily_offset(date(2026, 4, 8)) == 7.25

    def test_different_dates_independent(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_daily_offset(date(2026, 4, 8), 10.0)
        mgr.set_daily_offset(date(2026, 4, 9), 20.0)
        assert mgr.get_daily_offset(date(2026, 4, 8)) == 10.0
        assert mgr.get_daily_offset(date(2026, 4, 9)) == 20.0


# --- Alert tracking ---


class TestAlertTracking:
    def test_alert_not_fired_by_default(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.has_alert_fired_today(date(2026, 4, 8)) is False

    def test_mark_and_check_alert(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_alert_fired(date(2026, 4, 8))
        assert mgr.has_alert_fired_today(date(2026, 4, 8)) is True

    def test_alert_different_day_returns_false(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_alert_fired(date(2026, 4, 8))
        assert mgr.has_alert_fired_today(date(2026, 4, 9)) is False

    def test_alert_persists_to_disk(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_alert_fired(date(2026, 4, 8))

        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.has_alert_fired_today(date(2026, 4, 8)) is True


# --- Persistencia round-trip ---


class TestPersistence:
    def test_save_and_reload(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_daily_offset(date(2026, 4, 8), 5.0)
        mgr.mark_alert_fired(date(2026, 4, 8))
        mgr.save()

        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.get_daily_offset(date(2026, 4, 8)) == 5.0
        assert mgr2.has_alert_fired_today(date(2026, 4, 8)) is True
        assert mgr2.refresh_interval == REFRESH_INTERVAL_SECONDS


# --- API key ---


class TestApiKey:
    def test_default_empty(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.api_key == ""
        assert mgr.has_api_key is False
        assert mgr.api_key_type == ""

    def test_set_and_get_standard_key(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("sk-ant-api03-abc123")
        assert mgr.api_key == "sk-ant-api03-abc123"
        assert mgr.has_api_key is True
        assert mgr.api_key_type == "standard"

    def test_set_and_get_admin_key(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("sk-ant-admin01-xyz789")
        assert mgr.api_key_type == "admin"

    def test_unknown_key_type(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("some-random-key")
        assert mgr.api_key_type == "unknown"

    def test_clear_key(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("sk-ant-api03-abc123")
        mgr.set_api_key("")
        assert mgr.has_api_key is False

    def test_key_persists_to_disk(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("sk-ant-api03-persist")

        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.api_key == "sk-ant-api03-persist"

    def test_save_sets_restrictive_permissions(self, config_path):
        import stat

        mgr = ConfigManager(config_path=config_path)
        mgr.set_api_key("sk-ant-api03-secret")
        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestPlanConfig:
    def test_default_usage_mode_api(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.usage_mode == "api"

    def test_set_usage_mode_subscription(self, config_path):
        config_path.write_text(json.dumps({"usage_mode": "subscription"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.usage_mode == "subscription"

    def test_invalid_usage_mode_falls_back(self, config_path):
        config_path.write_text(json.dumps({"usage_mode": "invalid"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.usage_mode == "api"

    def test_default_plan(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.plan == "max_5x"

    def test_default_display_style(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.display_style == "bar"

    def test_toggle_display_style(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.display_style == "bar"
        mgr.toggle_display_style()
        assert mgr.display_style == "text"
        mgr.toggle_display_style()
        assert mgr.display_style == "bar"

    def test_daily_token_limits_from_plan(self, config_path):
        config_path.write_text(json.dumps({"plan": "max_5x"}))
        mgr = ConfigManager(config_path=config_path)
        limits = mgr.daily_token_limits
        assert "claude-opus-4-6" in limits
        assert limits["claude-opus-4-6"] > 0

    def test_custom_daily_token_limits_override(self, config_path):
        config_path.write_text(json.dumps({
            "plan": "max_5x",
            "daily_token_limits": {"claude-opus-4-6": 999},
        }))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.daily_token_limits["claude-opus-4-6"] == 999

    def test_set_plan(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_plan("max_20x")
        assert mgr.plan == "max_20x"
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.plan == "max_20x"

    def test_unknown_plan_uses_empty_limits(self, config_path):
        config_path.write_text(json.dumps({"plan": "nonexistent"}))
        mgr = ConfigManager(config_path=config_path)
        limits = mgr.daily_token_limits
        assert limits == {}



class TestExtraUsageConfig:
    def test_extra_usage_limit_default_zero(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.extra_usage_limit_usd == 0.0

    def test_extra_usage_alert_pct_default_90(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.extra_usage_alert_pct == 90.0

    def test_set_extra_usage_limit(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_limit(60.0)
        assert mgr.extra_usage_limit_usd == 60.0

    def test_set_extra_usage_limit_clamps_negative(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_limit(-10.0)
        assert mgr.extra_usage_limit_usd == 0.0

    def test_set_extra_usage_limit_ignores_inf(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_limit(60.0)
        mgr.set_extra_usage_limit(float("inf"))
        assert mgr.extra_usage_limit_usd == 60.0

    def test_set_extra_usage_limit_ignores_nan(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_limit(60.0)
        mgr.set_extra_usage_limit(float("nan"))
        assert mgr.extra_usage_limit_usd == 60.0

    def test_set_extra_usage_limit_persists(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_limit(40.0)
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.extra_usage_limit_usd == 40.0

    def test_set_extra_usage_alert_pct(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_alert_pct(80.0)
        assert mgr.extra_usage_alert_pct == 80.0

    def test_set_extra_usage_alert_pct_clamps_low(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_alert_pct(-5.0)
        assert mgr.extra_usage_alert_pct == 0.0

    def test_set_extra_usage_alert_pct_clamps_high(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_alert_pct(150.0)
        assert mgr.extra_usage_alert_pct == 100.0

    def test_set_extra_usage_alert_pct_persists(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_extra_usage_alert_pct(75.0)
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.extra_usage_alert_pct == 75.0

    def test_extra_alert_not_fired_by_default(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.has_extra_alert_fired_today(date(2026, 4, 9)) is False

    def test_mark_and_check_extra_alert(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_extra_alert_fired(date(2026, 4, 9))
        assert mgr.has_extra_alert_fired_today(date(2026, 4, 9)) is True

    def test_extra_alert_different_day(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_extra_alert_fired(date(2026, 4, 9))
        assert mgr.has_extra_alert_fired_today(date(2026, 4, 10)) is False

    def test_extra_alert_independent_from_cost_alert(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_alert_fired(date(2026, 4, 9))
        assert mgr.has_extra_alert_fired_today(date(2026, 4, 9)) is False

    def test_extra_alert_persists(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.mark_extra_alert_fired(date(2026, 4, 9))
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.has_extra_alert_fired_today(date(2026, 4, 9)) is True

    def test_load_extra_usage_from_file(self, config_path):
        config_path.write_text(json.dumps({
            "extra_usage_limit_usd": 100.0,
            "extra_usage_alert_pct": 85.0,
        }))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.extra_usage_limit_usd == 100.0
        assert mgr.extra_usage_alert_pct == 85.0


class TestSelectedModel:
    def test_default_none(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.selected_model is None

    def test_set_and_get(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_selected_model("claude-opus-4-6")
        assert mgr.selected_model == "claude-opus-4-6"

    def test_set_none_clears(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_selected_model("claude-opus-4-6")
        mgr.set_selected_model(None)
        assert mgr.selected_model is None

    def test_persists_to_disk(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_selected_model("claude-sonnet-4-6")
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.selected_model == "claude-sonnet-4-6"

    def test_empty_string_treated_as_none(self, config_path):
        config_path.write_text(json.dumps({"selected_model": ""}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.selected_model is None

    def test_load_from_file(self, config_path):
        config_path.write_text(json.dumps({"selected_model": "claude-opus-4-6"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.selected_model == "claude-opus-4-6"


class TestResetWindowConfig:
    def test_reset_window_hours_default(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_window_hours == 5

    def test_reset_window_hours_custom(self, config_path):
        config_path.write_text(json.dumps({"reset_window_hours": 3}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_window_hours == 3

    def test_reset_window_hours_clamped_low(self, config_path):
        config_path.write_text(json.dumps({"reset_window_hours": 0}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_window_hours == 1

    def test_reset_window_hours_clamped_high(self, config_path):
        config_path.write_text(json.dumps({"reset_window_hours": 30}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_window_hours == 24

    def test_reset_anchor_utc_default_none(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_anchor_utc is None

    def test_reset_anchor_utc_from_config(self, config_path):
        config_path.write_text(json.dumps({
            "reset_anchor_utc": "2026-04-09T15:00:00+00:00"
        }))
        mgr = ConfigManager(config_path=config_path)
        anchor = mgr.reset_anchor_utc
        assert anchor is not None
        assert anchor.year == 2026
        assert anchor.hour == 15

    def test_reset_anchor_utc_invalid_returns_none(self, config_path):
        config_path.write_text(json.dumps({"reset_anchor_utc": "not-a-date"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_anchor_utc is None

    def test_set_reset_anchor(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        anchor = datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)
        mgr.set_reset_anchor(anchor)
        assert mgr.reset_anchor_utc == anchor
        # Persiste
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.reset_anchor_utc == anchor

    def test_migration_from_reset_hour_utc(self, config_path):
        """Si existe reset_hour_utc pero no reset_anchor_utc, migra automáticamente."""
        config_path.write_text(json.dumps({"reset_hour_utc": 12}))
        mgr = ConfigManager(config_path=config_path)
        anchor = mgr.reset_anchor_utc
        assert anchor is not None
        assert anchor.hour == 12
        assert anchor.minute == 0

    def test_set_reset_anchor_removes_old_reset_hour(self, config_path):
        config_path.write_text(json.dumps({"reset_hour_utc": 7}))
        mgr = ConfigManager(config_path=config_path)
        anchor = datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)
        mgr.set_reset_anchor(anchor)
        # Ya no debería tener reset_hour_utc en raw data
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.reset_anchor_utc == anchor
        raw = json.loads(config_path.read_text())
        assert "reset_hour_utc" not in raw


class TestSubscription:
    def test_session_budget_default_max_5x(self, config_path):
        config_path.write_text(json.dumps({"plan": "max_5x"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.session_budget_usd == 20.26

    def test_session_budget_default_pro(self, config_path):
        config_path.write_text(json.dumps({"plan": "pro"}))
        mgr = ConfigManager(config_path=config_path)
        assert abs(mgr.session_budget_usd - 4.05) < 0.01

    def test_session_budget_default_max_20x(self, config_path):
        config_path.write_text(json.dumps({"plan": "max_20x"}))
        mgr = ConfigManager(config_path=config_path)
        assert abs(mgr.session_budget_usd - 81.04) < 0.01

    def test_session_budget_custom_override(self, config_path):
        config_path.write_text(json.dumps({
            "plan": "max_5x",
            "session_budget_usd": 15.0,
        }))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.session_budget_usd == 15.0

    def test_session_budget_unknown_plan_fallback(self, config_path):
        config_path.write_text(json.dumps({"plan": "nonexistent"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.session_budget_usd == 20.26

    def test_set_session_budget(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_session_budget(15.5)
        assert mgr.session_budget_usd == 15.5
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.session_budget_usd == 15.5

    def test_set_plan_clears_custom_budget(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_session_budget(15.0)
        mgr.set_plan("pro")
        assert abs(mgr.session_budget_usd - 4.05) < 0.01
