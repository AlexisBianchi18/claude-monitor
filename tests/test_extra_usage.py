"""Tests para extra usage — modelo y funcion de calculo."""

from claude_monitor.models import ExtraUsageStatus


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
