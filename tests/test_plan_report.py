"""Tests para get_plan_report — modo suscripcion (cost-based)."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_monitor.log_parser import ClaudeLogParser
from claude_monitor.models import PlanReport


TARGET_DATE = date(2026, 4, 8)
RESET_ANCHOR = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
WINDOW_HOURS = 5
TEST_NOW = datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc)
SESSION_BUDGET = 11.48


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
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        assert isinstance(report, PlanReport)
        assert report.plan_name == "max_5x"
        assert report.session_budget_usd == SESSION_BUDGET

    def test_model_costs(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        by_model = {m.model: m for m in report.models}
        assert by_model["claude-opus-4-6"].cost_usd > 0
        assert by_model["claude-sonnet-4-6"].cost_usd > 0
        assert by_model["claude-haiku-4-5-20251001"].cost_usd > 0
        # Per-model percentages should sum to overall
        model_sum = sum(m.percentage for m in report.models)
        assert abs(model_sum - report.overall_percentage) < 0.01

    def test_overall_percentage_matches_cost_ratio(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        expected_pct = (report.equivalent_api_cost / SESSION_BUDGET) * 100.0
        assert abs(report.overall_percentage - expected_pct) < 0.01

    def test_equivalent_api_cost(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        daily = parser.get_daily_report(TARGET_DATE)
        assert abs(report.equivalent_api_cost - daily.total_cost) < 1e-10

    def test_estimated_reset_in_window(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        assert report.estimated_reset is not None
        assert report.estimated_reset == datetime(2026, 4, 8, 17, 0, tzinfo=timezone.utc)
        assert report.estimated_reset > TEST_NOW

    def test_empty_logs_returns_zero_report(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent"))
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=RESET_ANCHOR,
            reset_window_hours=WINDOW_HOURS,
            _now=TEST_NOW,
        )
        assert report.overall_percentage == 0.0
        assert report.equivalent_api_cost == 0.0
        assert len(report.models) == 0

    def test_fallback_to_daily_without_anchor(self, logs_with_usage):
        parser = ClaudeLogParser(logs_dir=logs_with_usage)
        report = parser.get_plan_report(
            plan_name="max_5x",
            session_budget_usd=SESSION_BUDGET,
            reset_anchor_utc=None,
            target_date=TARGET_DATE,
        )
        assert len(report.models) > 0
        assert report.equivalent_api_cost > 0
        assert report.estimated_reset is None
