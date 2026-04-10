"""Tests para extra usage — modelo y funcion de calculo."""

from datetime import datetime, timezone

from claude_monitor.extra_usage import calculate_extra_usage
from claude_monitor.models import ExtraUsageStatus, PlanReport


class TestExtraUsageStatus:
    def test_percentage_normal(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=12.0, alert_threshold_pct=90.0)
        assert abs(s.percentage - 20.0) < 0.01

    def test_percentage_zero_limit(self):
        s = ExtraUsageStatus(limit_usd=0.0, cost_usd=5.0, alert_threshold_pct=90.0)
        assert s.percentage == 0.0

    def test_percentage_zero_cost(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=0.0, alert_threshold_pct=90.0)
        assert s.percentage == 0.0

    def test_remaining_usd(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=12.0, alert_threshold_pct=90.0)
        assert abs(s.remaining_usd - 48.0) < 0.01

    def test_remaining_usd_clamped_to_zero(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=75.0, alert_threshold_pct=90.0)
        assert s.remaining_usd == 0.0

    def test_is_over_alert_below(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=50.0, alert_threshold_pct=90.0)
        assert s.is_over_alert is False

    def test_is_over_alert_at_threshold(self):
        s = ExtraUsageStatus(limit_usd=100.0, cost_usd=90.0, alert_threshold_pct=90.0)
        assert s.is_over_alert is True

    def test_is_over_alert_above(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=58.0, alert_threshold_pct=90.0)
        assert s.is_over_alert is True

    def test_is_exhausted_below(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=59.99, alert_threshold_pct=90.0)
        assert s.is_exhausted is False

    def test_is_exhausted_at_limit(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=60.0, alert_threshold_pct=90.0)
        assert s.is_exhausted is True

    def test_is_exhausted_over_limit(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=65.0, alert_threshold_pct=90.0)
        assert s.is_exhausted is True

    def test_is_exhausted_zero_limit(self):
        s = ExtraUsageStatus(limit_usd=0.0, cost_usd=0.0, alert_threshold_pct=90.0)
        assert s.is_exhausted is False

    def test_percentage_over_100(self):
        s = ExtraUsageStatus(limit_usd=60.0, cost_usd=90.0, alert_threshold_pct=90.0)
        assert abs(s.percentage - 150.0) < 0.01


def _make_plan_report(
    equivalent_api_cost: float = 0.0,
    session_budget_usd: float = 10.0,
) -> PlanReport:
    return PlanReport(
        plan_name="max_5x",
        models=[],
        estimated_reset=datetime(2026, 4, 9, 7, 0, 0, tzinfo=timezone.utc),
        equivalent_api_cost=equivalent_api_cost,
        session_budget_usd=session_budget_usd,
    )


class TestCalculateExtraUsage:
    def test_returns_none_when_limit_negative(self):
        report = _make_plan_report(equivalent_api_cost=15.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=-1.0, alert_threshold_pct=90.0)
        assert result is None

    def test_returns_none_when_limit_zero(self):
        report = _make_plan_report(equivalent_api_cost=15.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=0.0, alert_threshold_pct=90.0)
        assert result is None

    def test_returns_none_when_below_100_pct(self):
        report = _make_plan_report(equivalent_api_cost=5.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is None

    def test_returns_status_when_over_100_pct(self):
        report = _make_plan_report(equivalent_api_cost=15.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is not None
        assert isinstance(result, ExtraUsageStatus)
        assert result.limit_usd == 60.0

    def test_extra_cost_calculation(self):
        # budget=10, cost=15 -> extra = 15-10 = $5.00
        report = _make_plan_report(equivalent_api_cost=15.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is not None
        assert abs(result.cost_usd - 5.0) < 0.01

    def test_alert_threshold_passed_through(self):
        report = _make_plan_report(equivalent_api_cost=15.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=80.0)
        assert result is not None
        assert result.alert_threshold_pct == 80.0

    def test_zero_cost(self):
        report = _make_plan_report(equivalent_api_cost=0.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is None

    def test_exact_100_pct_triggers(self):
        # cost == budget -> 100% -> triggers, but extra_cost = 0
        report = _make_plan_report(equivalent_api_cost=10.0, session_budget_usd=10.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is not None
        assert result.cost_usd == 0.0

    def test_zero_budget(self):
        report = _make_plan_report(equivalent_api_cost=0.0, session_budget_usd=0.0)
        result = calculate_extra_usage(report, extra_limit_usd=60.0, alert_threshold_pct=90.0)
        assert result is None
