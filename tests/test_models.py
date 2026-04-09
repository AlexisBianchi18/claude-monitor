"""Tests para models.py."""

from datetime import date, datetime, timedelta, timezone

from claude_monitor.models import (
    ApiCostReport,
    CostEntry,
    DailyReport,
    ModelUsageStatus,
    PlanReport,
    ProjectStats,
    RateLimitInfo,
    TokenUsage,
)


class TestTokenUsage:
    def test_defaults_all_zero(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.cache_read_input_tokens == 0
        assert u.cache_creation_input_tokens == 0
        assert u.total_tokens == 0

    def test_total_tokens_sums_all_fields(self):
        u = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=200,
        )
        assert u.total_tokens == 850

    def test_partial_fields(self):
        u = TokenUsage(input_tokens=10, output_tokens=20)
        assert u.total_tokens == 30


class TestCostEntry:
    def test_creation(self):
        ts = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        entry = CostEntry(
            message_id="msg_001",
            model="claude-opus-4-6",
            usage=usage,
            cost_usd=0.05,
            timestamp=ts,
        )
        assert entry.message_id == "msg_001"
        assert entry.model == "claude-opus-4-6"
        assert entry.cost_usd == 0.05
        assert entry.timestamp == ts


class TestProjectStats:
    def test_defaults(self):
        ps = ProjectStats(name="test", display_name="test", dir_name="encoded")
        assert ps.total_cost == 0.0
        assert ps.total_tokens == 0
        assert ps.entry_count == 0


class TestDailyReport:
    def test_defaults(self):
        r = DailyReport(date=date(2026, 4, 8))
        assert r.total_cost == 0.0
        assert r.total_tokens == 0
        assert r.entry_count == 0
        assert r.projects == []
        assert r.models_used == set()

    def test_models_used(self):
        r = DailyReport(
            date=date(2026, 4, 8),
            models_used={"claude-opus-4-6", "claude-sonnet-4-6"},
        )
        assert r.models_used == {"claude-opus-4-6", "claude-sonnet-4-6"}


class TestRateLimitInfo:
    def _make(self, limit=1000, remaining=600, reset_offset_secs=45, model="claude-sonnet-4-6"):
        from datetime import timedelta

        reset = datetime.now(timezone.utc) + timedelta(seconds=reset_offset_secs)
        return RateLimitInfo(
            model=model,
            tokens_limit=limit,
            tokens_remaining=remaining,
            tokens_reset=reset,
        )

    def test_usage_pct_zero(self):
        info = self._make(limit=1000, remaining=1000)
        assert info.usage_pct == 0.0

    def test_usage_pct_half(self):
        info = self._make(limit=1000, remaining=500)
        assert info.usage_pct == 50.0

    def test_usage_pct_full(self):
        info = self._make(limit=1000, remaining=0)
        assert info.usage_pct == 100.0

    def test_usage_pct_zero_limit(self):
        info = self._make(limit=0, remaining=0)
        assert info.usage_pct == 0.0

    def test_seconds_until_reset_future(self):
        info = self._make(reset_offset_secs=60)
        secs = info.seconds_until_reset
        assert 58 <= secs <= 60

    def test_seconds_until_reset_past(self):
        info = self._make(reset_offset_secs=-10)
        assert info.seconds_until_reset == 0

    def test_seconds_until_reset_now(self):
        info = self._make(reset_offset_secs=0)
        assert info.seconds_until_reset == 0

    def test_default_fetched_at(self):
        info = self._make()
        assert info.fetched_at is not None
        age = (datetime.now(timezone.utc) - info.fetched_at).total_seconds()
        assert age < 2


class TestApiCostReport:
    def test_creation(self):
        r = ApiCostReport(date=date(2026, 4, 8), total_cost_usd=1.23)
        assert r.date == date(2026, 4, 8)
        assert r.total_cost_usd == 1.23

    def test_default_fetched_at(self):
        r = ApiCostReport(date=date(2026, 4, 8), total_cost_usd=0.0)
        age = (datetime.now(timezone.utc) - r.fetched_at).total_seconds()
        assert age < 2


class TestModelUsageStatus:
    def test_from_values(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            tokens_used=4_000_000,
            tokens_limit=10_000_000,
        )
        assert status.percentage == 40.0
        assert status.tokens_remaining == 6_000_000

    def test_zero_limit(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            tokens_used=100,
            tokens_limit=0,
        )
        assert status.percentage == 0.0
        assert status.tokens_remaining == 0

    def test_over_limit(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            tokens_used=12_000_000,
            tokens_limit=10_000_000,
        )
        assert status.percentage == 120.0
        assert status.tokens_remaining == 0


class TestPlanReport:
    def test_overall_percentage(self):
        models = [
            ModelUsageStatus(model="a", tokens_used=5_000_000, tokens_limit=10_000_000),
            ModelUsageStatus(model="b", tokens_used=3_000_000, tokens_limit=10_000_000),
        ]
        report = PlanReport(
            plan_name="max_5x",
            models=models,
            estimated_reset=None,
            equivalent_api_cost=12.50,
        )
        assert report.overall_percentage == 40.0

    def test_overall_percentage_no_models(self):
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=None,
            equivalent_api_cost=0.0,
        )
        assert report.overall_percentage == 0.0

    def test_seconds_until_reset(self):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=future,
            equivalent_api_cost=0.0,
        )
        secs = report.seconds_until_reset
        assert 7100 < secs <= 7200

    def test_seconds_until_reset_none(self):
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=None,
            equivalent_api_cost=0.0,
        )
        assert report.seconds_until_reset == 0
