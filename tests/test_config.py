"""Tests para ConfigManager — configuración persistente."""

import json
from datetime import date
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
