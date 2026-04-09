"""Tests para get_plan_report — modo suscripcion."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_monitor.log_parser import ClaudeLogParser
from claude_monitor.models import PlanReport


TARGET_DATE = date(2026, 4, 8)

PLAN_LIMITS = {
    "claude-opus-4-6": 10_000_000,
    "claude-sonnet-4-6": 50_000_000,
    "claude-haiku-4-5-20251001": 150_000_000,
}


def _make_entry(model: str, msg_id: str, input_tok: int, output_tok: int) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "model": model,
            "id": msg_id,
            "usage": {
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
        "timestamp": "2026-04-08T14:00:00.000Z",
    })


@pytest.fixture()
def logs_with_usage(tmp_path):
    project_dir = tmp_path / "-Users-test-project"
    project_dir.mkdir()
    session = project_dir / "session.jsonl"
    lines = [
        json.dumps({
            "type": "user",
            "message": {"role": "user", "content": []},
            "cwd": "/Users/test/project",
            "timestamp": "2026-04-08T13:00:00.000Z",
        }),
        _make_entry("claude-opus-4-6", "msg_o1", 500_000, 100_000),
        _make_entry("claude-sonnet-4-6", "msg_s1", 2_000_000, 500_000),
        _make_entry("claude-haiku-4-5-20251001", "msg_h1", 10_000_000, 3_000_000),
    ]
    session.write_text("\n".join(lines) + "\n")
    return tmp_path


class TestGetPlanReport:
    def test_returns_plan_report(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            daily_limits=PLAN_LIMITS,
            reset_hour_utc=7,
            target_date=TARGET_DATE,
        )
        assert isinstance(report, PlanReport)
        assert report.plan_name == "max_5x"

    def test_model_percentages(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            daily_limits=PLAN_LIMITS,
            reset_hour_utc=7,
            target_date=TARGET_DATE,
        )
        by_model = {m.model: m for m in report.models}
        # opus: 600K used / 10M limit = 6%
        assert by_model["claude-opus-4-6"].tokens_used == 600_000
        assert abs(by_model["claude-opus-4-6"].percentage - 6.0) < 0.1
        # sonnet: 2.5M used / 50M limit = 5%
        assert by_model["claude-sonnet-4-6"].tokens_used == 2_500_000
        # haiku: 13M used / 150M limit ~= 8.67%
        assert by_model["claude-haiku-4-5-20251001"].tokens_used == 13_000_000

    def test_equivalent_api_cost(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            daily_limits=PLAN_LIMITS,
            reset_hour_utc=7,
            target_date=TARGET_DATE,
        )
        daily = parser.get_daily_report(TARGET_DATE)
        assert abs(report.equivalent_api_cost - daily.total_cost) < 1e-10

    def test_estimated_reset_is_in_future(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            daily_limits=PLAN_LIMITS,
            reset_hour_utc=7,
            target_date=TARGET_DATE,
        )
        assert report.estimated_reset is not None
        assert report.estimated_reset > datetime.now(timezone.utc)

    def test_empty_logs_returns_zero_report(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent"))
        report = parser.get_plan_report(
            plan_name="max_5x",
            daily_limits=PLAN_LIMITS,
            reset_hour_utc=7,
        )
        assert report.overall_percentage == 0.0
        assert report.equivalent_api_cost == 0.0
        assert report.models == []

    def test_models_only_for_configured_limits(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        limited = {"claude-opus-4-6": 10_000_000}
        report = parser.get_plan_report(
            plan_name="custom",
            daily_limits=limited,
            reset_hour_utc=7,
            target_date=TARGET_DATE,
        )
        model_names = [m.model for m in report.models]
        assert "claude-opus-4-6" in model_names
        assert "claude-sonnet-4-6" not in model_names
