"""Tests para models.py."""

from datetime import date, datetime, timezone

from claude_monitor.models import (
    CostEntry,
    DailyReport,
    ProjectStats,
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
