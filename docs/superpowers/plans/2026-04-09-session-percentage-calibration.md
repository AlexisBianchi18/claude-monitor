# Session Percentage Calibration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace token-based percentage calculation with cost-based session budget so the app's session % matches claude.ai.

**Architecture:** Introduce `SESSION_BUDGETS` (USD per plan per 5h window) and change `ModelUsageStatus` / `PlanReport` to use cost instead of token counts. The parser's `get_plan_report()` receives a budget instead of token limits. A calibration mechanism lets the user align the budget with claude.ai's real percentage.

**Tech Stack:** Python 3.11+, rumps, pytest, uv

---

### Task 1: Update `ModelUsageStatus` dataclass

**Files:**
- Modify: `claude_monitor/models.py:119-135`
- Test: `tests/test_models.py:154-180`

- [ ] **Step 1: Write failing tests for new ModelUsageStatus**

Replace the existing `TestModelUsageStatus` class in `tests/test_models.py:154-180`:

```python
class TestModelUsageStatus:
    def test_from_values(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            cost_usd=4.0,
            session_budget_usd=10.0,
        )
        assert status.percentage == 40.0

    def test_zero_budget(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            cost_usd=1.0,
            session_budget_usd=0.0,
        )
        assert status.percentage == 0.0

    def test_over_budget(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            cost_usd=12.0,
            session_budget_usd=10.0,
        )
        assert status.percentage == 120.0

    def test_negative_budget(self):
        status = ModelUsageStatus(
            model="claude-opus-4-6",
            cost_usd=5.0,
            session_budget_usd=-1.0,
        )
        assert status.percentage == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestModelUsageStatus -v`
Expected: FAIL — `ModelUsageStatus.__init__() got unexpected keyword argument 'cost_usd'`

- [ ] **Step 3: Update ModelUsageStatus implementation**

Replace `claude_monitor/models.py:119-135` with:

```python
@dataclass
class ModelUsageStatus:
    """Estado de uso de un modelo en el periodo actual (basado en costo)."""

    model: str
    cost_usd: float
    session_budget_usd: float

    @property
    def percentage(self) -> float:
        if self.session_budget_usd <= 0:
            return 0.0
        return (self.cost_usd / self.session_budget_usd) * 100.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py::TestModelUsageStatus -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/models.py tests/test_models.py
git commit -m "refactor: ModelUsageStatus from token-based to cost-based"
```

---

### Task 2: Update `PlanReport` dataclass

**Files:**
- Modify: `claude_monitor/models.py:138-160`
- Test: `tests/test_models.py:183-224`

- [ ] **Step 1: Write failing tests for new PlanReport**

Replace the existing `TestPlanReport` class in `tests/test_models.py:183-224`:

```python
class TestPlanReport:
    def test_overall_percentage(self):
        models = [
            ModelUsageStatus(model="a", cost_usd=3.0, session_budget_usd=10.0),
            ModelUsageStatus(model="b", cost_usd=1.0, session_budget_usd=10.0),
        ]
        report = PlanReport(
            plan_name="max_5x",
            models=models,
            estimated_reset=None,
            equivalent_api_cost=4.0,
            session_budget_usd=10.0,
        )
        assert report.overall_percentage == 40.0

    def test_overall_percentage_no_models(self):
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=None,
            equivalent_api_cost=0.0,
            session_budget_usd=10.0,
        )
        assert report.overall_percentage == 0.0

    def test_overall_percentage_zero_budget(self):
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=None,
            equivalent_api_cost=5.0,
            session_budget_usd=0.0,
        )
        assert report.overall_percentage == 0.0

    def test_seconds_until_reset(self):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=future,
            equivalent_api_cost=0.0,
            session_budget_usd=10.0,
        )
        secs = report.seconds_until_reset
        assert 7100 < secs <= 7200

    def test_seconds_until_reset_none(self):
        report = PlanReport(
            plan_name="max_5x",
            models=[],
            estimated_reset=None,
            equivalent_api_cost=0.0,
            session_budget_usd=10.0,
        )
        assert report.seconds_until_reset == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestPlanReport -v`
Expected: FAIL — `PlanReport.__init__() got unexpected keyword argument 'session_budget_usd'`

- [ ] **Step 3: Update PlanReport implementation**

Replace `claude_monitor/models.py:138-160` with:

```python
@dataclass
class PlanReport:
    """Reporte de uso del plan de suscripcion."""

    plan_name: str
    models: list[ModelUsageStatus]
    estimated_reset: datetime | None
    equivalent_api_cost: float
    session_budget_usd: float

    @property
    def overall_percentage(self) -> float:
        if self.session_budget_usd <= 0:
            return 0.0
        return (self.equivalent_api_cost / self.session_budget_usd) * 100.0

    @property
    def seconds_until_reset(self) -> int:
        if self.estimated_reset is None:
            return 0
        delta = self.estimated_reset - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py::TestPlanReport -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/models.py tests/test_models.py
git commit -m "refactor: PlanReport from token-based to cost-based percentage"
```

---

### Task 3: Add `SESSION_BUDGETS` and config properties

**Files:**
- Modify: `claude_monitor/config.py:56-73` (add SESSION_BUDGETS after PLAN_LIMITS)
- Modify: `claude_monitor/config.py:240-253` (add session_budget properties)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py` in the `TestSubscription` section (after the existing `test_daily_token_limits` tests):

```python
    def test_session_budget_default_max_5x(self, config_path):
        config_path.write_text(json.dumps({"plan": "max_5x"}))
        mgr = ConfigManager(config_path=config_path)
        assert mgr.session_budget_usd == 11.48

    def test_session_budget_default_pro(self, config_path):
        config_path.write_text(json.dumps({"plan": "pro"}))
        mgr = ConfigManager(config_path=config_path)
        assert abs(mgr.session_budget_usd - 2.30) < 0.01

    def test_session_budget_default_max_20x(self, config_path):
        config_path.write_text(json.dumps({"plan": "max_20x"}))
        mgr = ConfigManager(config_path=config_path)
        assert abs(mgr.session_budget_usd - 45.92) < 0.01

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
        assert mgr.session_budget_usd == 11.48

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
        assert mgr.session_budget_usd == 2.30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py::TestSubscription::test_session_budget_default_max_5x -v`
Expected: FAIL — `AttributeError: 'ConfigManager' object has no attribute 'session_budget_usd'`

- [ ] **Step 3: Add SESSION_BUDGETS constant**

Add after `PLAN_LIMITS` in `claude_monitor/config.py` (after line 73):

```python
# Presupuestos de sesion en USD-equivalentes por ventana de 5h.
# Calibrado 2026-04-09: Max 5x = $11.48 (medido vs claude.ai 31%).
SESSION_BUDGETS: dict[str, float] = {
    "pro": 2.30,
    "max_5x": 11.48,
    "max_20x": 45.92,
}
```

- [ ] **Step 4: Add session_budget properties to ConfigManager**

Add after the `set_plan` method in `claude_monitor/config.py` (after line 253):

```python
    @property
    def session_budget_usd(self) -> float:
        """Presupuesto de sesion en USD. Custom override o default por plan."""
        custom = self._data.get("session_budget_usd")
        if custom is not None:
            return float(custom)
        return SESSION_BUDGETS.get(self.plan, 11.48)

    def set_session_budget(self, budget: float) -> None:
        """Guarda un presupuesto de sesion custom y persiste."""
        self._data["session_budget_usd"] = budget
        self.save()
```

Also update `set_plan` to clear custom budget — change `claude_monitor/config.py:249-253`:

```python
    def set_plan(self, plan: str) -> None:
        """Cambia el plan y persiste. Limpia custom limits y budget."""
        self._data["plan"] = plan
        self._data.pop("daily_token_limits", None)
        self._data.pop("session_budget_usd", None)
        self.save()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k "session_budget" -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add claude_monitor/config.py tests/test_config.py
git commit -m "feat: add SESSION_BUDGETS and session_budget_usd config"
```

---

### Task 4: Update `get_plan_report()` in log_parser

**Files:**
- Modify: `claude_monitor/log_parser.py:137-178`
- Test: `tests/test_plan_report.py`

- [ ] **Step 1: Rewrite test file for new signature**

Replace `tests/test_plan_report.py` entirely:

```python
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
        # Each model should have cost_usd > 0
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plan_report.py -v`
Expected: FAIL — `get_plan_report() got unexpected keyword argument 'session_budget_usd'`

- [ ] **Step 3: Update get_plan_report() implementation**

Replace `claude_monitor/log_parser.py:137-178`:

```python
    def get_plan_report(
        self,
        plan_name: str,
        session_budget_usd: float,
        reset_anchor_utc: datetime | None = None,
        reset_window_hours: int = 5,
        target_date: date | None = None,
        *,
        _now: datetime | None = None,
    ) -> PlanReport:
        """Genera un reporte de uso para modo suscripcion (basado en costo)."""
        if reset_anchor_utc is not None:
            window_start, window_end = self._compute_window_boundaries(
                reset_anchor_utc, reset_window_hours, _now=_now
            )
            window_report = self.get_window_report(window_start, window_end)
            cost_by_model = window_report.cost_by_model
            equivalent_cost = window_report.total_cost
        else:
            daily = self.get_daily_report(target_date)
            cost_by_model = daily.cost_by_model
            equivalent_cost = daily.total_cost

        models: list[ModelUsageStatus] = []
        for model, cost in sorted(cost_by_model.items()):
            models.append(ModelUsageStatus(
                model=model,
                cost_usd=cost,
                session_budget_usd=session_budget_usd,
            ))

        estimated_reset = self._estimate_next_reset(
            reset_anchor_utc, reset_window_hours, _now=_now
        )

        return PlanReport(
            plan_name=plan_name,
            models=models,
            estimated_reset=estimated_reset,
            equivalent_api_cost=equivalent_cost,
            session_budget_usd=session_budget_usd,
        )
```

Make sure the `ModelUsageStatus` import at the top of `log_parser.py` is present (it should already be).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan_report.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/log_parser.py tests/test_plan_report.py
git commit -m "refactor: get_plan_report uses session_budget_usd instead of daily_limits"
```

---

### Task 5: Update `extra_usage.py`

**Files:**
- Modify: `claude_monitor/extra_usage.py:8-38`
- Test: `tests/test_extra_usage.py:63-173`

- [ ] **Step 1: Rewrite helper and tests for cost-based PlanReport**

Replace `_make_plan_report` and `TestCalculateExtraUsage` in `tests/test_extra_usage.py:63-173`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_extra_usage.py::TestCalculateExtraUsage -v`
Expected: FAIL — `PlanReport.__init__() got unexpected keyword argument 'session_budget_usd'` (if Tasks 1-2 already applied) or mismatched fields

- [ ] **Step 3: Update calculate_extra_usage implementation**

Replace `claude_monitor/extra_usage.py` entirely:

```python
"""Calculo de extra usage para modo subscription."""

from __future__ import annotations

from .models import ExtraUsageStatus, PlanReport


def calculate_extra_usage(
    plan_report: PlanReport,
    extra_limit_usd: float,
    alert_threshold_pct: float,
) -> ExtraUsageStatus | None:
    """Calcula el estado de extra usage.

    Retorna None si no aplica (sin budget extra o plan no agotado).
    """
    if extra_limit_usd <= 0:
        return None
    if plan_report.overall_percentage < 100.0:
        return None

    extra_cost = max(
        0.0,
        plan_report.equivalent_api_cost - plan_report.session_budget_usd,
    )

    return ExtraUsageStatus(
        limit_usd=extra_limit_usd,
        cost_usd=extra_cost,
        alert_threshold_pct=alert_threshold_pct,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_extra_usage.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/extra_usage.py tests/test_extra_usage.py
git commit -m "refactor: extra_usage uses cost-based PlanReport"
```

---

### Task 6: Update `app.py` — subscription refresh and menu

**Files:**
- Modify: `claude_monitor/app.py:428-434` (get_plan_report call)
- Modify: `claude_monitor/app.py:516-531` (model menu items)

- [ ] **Step 1: Update get_plan_report call in _refresh_subscription**

Change `claude_monitor/app.py:428-434` from:

```python
        plan_report = self.parser.get_plan_report(
            plan_name=self.config.plan,
            daily_limits=self.config.daily_token_limits,
            reset_anchor_utc=self.config.reset_anchor_utc,
            reset_window_hours=self.config.reset_window_hours,
            target_date=today,
        )
```

to:

```python
        plan_report = self.parser.get_plan_report(
            plan_name=self.config.plan,
            session_budget_usd=self.config.session_budget_usd,
            reset_anchor_utc=self.config.reset_anchor_utc,
            reset_window_hours=self.config.reset_window_hours,
            target_date=today,
        )
```

- [ ] **Step 2: Update per-model menu items in _update_subscription_menu**

Change `claude_monitor/app.py:519-525` (the model rendering inside the loop) from:

```python
            if style == "bar":
                bar = _render_bar(m.percentage)
                line = f"{prefix} {short_name:<14}{bar} {m.percentage:>5.1f}%"
            else:
                used_str = _format_tokens_short(m.tokens_used)
                limit_str = _format_tokens_short(m.tokens_limit)
                line = f"{prefix} {short_name:<14}{used_str:>5} / {limit_str:<5}"
```

to:

```python
            if style == "bar":
                bar = _render_bar(m.percentage)
                line = f"{prefix} {short_name:<14}{bar} {m.percentage:>5.1f}%"
            else:
                budget_str = f"${m.session_budget_usd:.2f}"
                line = f"{prefix} {short_name:<14}${m.cost_usd:.2f} / {budget_str}"
```

- [ ] **Step 3: Run full test suite to check nothing else breaks**

Run: `uv run pytest -v`
Expected: All tests PASS. If any test referencing old `ModelUsageStatus` or `PlanReport` fields fails, fix it.

- [ ] **Step 4: Commit**

```bash
git add claude_monitor/app.py
git commit -m "feat: app.py uses cost-based session budget for subscription mode"
```

---

### Task 7: Update `cli.py` — subscription report display

**Files:**
- Modify: `claude_monitor/cli.py:90-111` (_print_plan_report)
- Modify: `claude_monitor/cli.py:136-143` (main, get_plan_report call)

- [ ] **Step 1: Update _print_plan_report for cost-based display**

Change `claude_monitor/cli.py:96-104` from:

```python
    for m in report.models:
        short_name = m.model.replace("claude-", "").replace("-20251001", "")
        if style == "bar":
            bar = _render_bar(m.percentage)
            print(f"  {short_name:<20} {bar}  {m.percentage:.1f}%")
        else:
            used = _format_tokens_short(m.tokens_used)
            limit = _format_tokens_short(m.tokens_limit)
            print(f"  {short_name:<20} {used} / {limit}")
```

to:

```python
    for m in report.models:
        short_name = m.model.replace("claude-", "").replace("-20251001", "")
        if style == "bar":
            bar = _render_bar(m.percentage)
            print(f"  {short_name:<20} {bar}  {m.percentage:.1f}%")
        else:
            print(f"  {short_name:<20} ${m.cost_usd:.2f} / ${m.session_budget_usd:.2f}")
```

- [ ] **Step 2: Update main() get_plan_report call**

Change `claude_monitor/cli.py:137-143` from:

```python
        report = parser.get_plan_report(
            plan_name=config.plan,
            daily_limits=config.daily_token_limits,
            reset_anchor_utc=config.reset_anchor_utc,
            reset_window_hours=config.reset_window_hours,
            target_date=today,
        )
```

to:

```python
        report = parser.get_plan_report(
            plan_name=config.plan,
            session_budget_usd=config.session_budget_usd,
            reset_anchor_utc=config.reset_anchor_utc,
            reset_window_hours=config.reset_window_hours,
            target_date=today,
        )
```

- [ ] **Step 3: Run CLI to verify output looks correct**

Run: `uv run python -m claude_monitor.cli`
Expected: Output shows percentages based on cost (e.g., `opus-4-6  ▰▰▰▱▱▱▱▱▱▱  26.1%`)

- [ ] **Step 4: Commit**

```bash
git add claude_monitor/cli.py
git commit -m "feat: cli.py uses cost-based session budget"
```

---

### Task 8: Add calibration to CLI

**Files:**
- Modify: `claude_monitor/cli.py` (add --calibrate and --reset-in args)
- Modify: `claude_monitor/config.py` (add set_reset_anchor_from_minutes)

- [ ] **Step 1: Add calibrate arguments to argparse**

In `claude_monitor/cli.py`, add after the `--update-prices` argument (line 119):

```python
    ap.add_argument(
        "--calibrate",
        type=float,
        metavar="PCT",
        help="Calibrate session budget using the %% shown on claude.ai",
    )
    ap.add_argument(
        "--reset-in",
        type=int,
        metavar="MIN",
        help="Calibrate reset anchor using minutes until reset from claude.ai",
    )
```

- [ ] **Step 2: Add calibration logic to main()**

Add after the `--update-prices` handler block (after line 131, before `config = ConfigManager()`):

```python
    if args.calibrate is not None:
        config = ConfigManager()
        pct = args.calibrate
        if not (1.0 <= pct <= 100.0):
            print("Error: percentage must be between 1 and 100.")
            return

        parser = ClaudeLogParser()
        anchor = config.reset_anchor_utc
        window_hours = config.reset_window_hours
        if anchor is not None:
            start, end = ClaudeLogParser._compute_window_boundaries(
                anchor, window_hours
            )
            window_report = parser.get_window_report(start, end)
            current_cost = window_report.total_cost
        else:
            daily = parser.get_daily_report(date.today())
            current_cost = daily.total_cost

        if current_cost <= 0:
            print("Error: no usage in current window. Use some tokens first.")
            return

        old_budget = config.session_budget_usd
        new_budget = current_cost / (pct / 100.0)
        config.set_session_budget(new_budget)
        print(f"Session budget calibrated: ${new_budget:.2f} (was ${old_budget:.2f})")

        if args.reset_in is not None:
            minutes = args.reset_in
            if minutes <= 0:
                print("Error: minutes must be positive.")
                return
            from datetime import datetime as dt, timedelta, timezone
            now = dt.now(timezone.utc)
            next_reset = now + timedelta(minutes=minutes)
            new_anchor = next_reset - timedelta(hours=window_hours)
            config.set_reset_anchor(new_anchor)
            print(f"Reset anchor calibrated: {new_anchor.isoformat()}")

        return
```

- [ ] **Step 3: Test calibration manually**

Run: `uv run python -m claude_monitor.cli --calibrate 31`
Expected: `Session budget calibrated: $X.XX (was $11.48)`

Run: `uv run python -m claude_monitor.cli --calibrate 31 --reset-in 142`
Expected: Both budget and anchor calibrated.

- [ ] **Step 4: Verify the calibrated output**

Run: `uv run python -m claude_monitor.cli`
Expected: Overall percentage is close to what claude.ai showed.

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/cli.py
git commit -m "feat: add --calibrate and --reset-in CLI flags for session calibration"
```

---

### Task 9: Add Calibrate menu item to app.py

**Files:**
- Modify: `claude_monitor/app.py` (add calibrate item in preferences or subscription menu)

- [ ] **Step 1: Add _on_calibrate callback**

Add a new method to `ClaudeMonitorApp`:

```python
    def _on_calibrate(self, _sender):
        """Dialogo para calibrar session budget con % de claude.ai."""
        response = rumps.Window(
            title="Calibrate Session Budget",
            message="Enter the session % shown on claude.ai/settings/usage:",
            default_text="",
            ok="Calibrate",
            cancel="Cancel",
            dimensions=(200, 24),
        ).run()
        if not response.clicked:
            return
        try:
            pct = float(response.text.strip().replace("%", ""))
        except (ValueError, AttributeError):
            rumps.alert("Invalid input", "Please enter a number (e.g., 31)")
            return
        if not (1.0 <= pct <= 100.0):
            rumps.alert("Invalid range", "Percentage must be between 1 and 100")
            return

        anchor = self.config.reset_anchor_utc
        window_hours = self.config.reset_window_hours
        if anchor is not None:
            start, end = ClaudeLogParser._compute_window_boundaries(
                anchor, window_hours
            )
            window_report = self.parser.get_window_report(start, end)
            current_cost = window_report.total_cost
        else:
            daily = self.parser.get_daily_report(date.today())
            current_cost = daily.total_cost

        if current_cost <= 0:
            rumps.alert("No usage", "No token usage in current window. Use some tokens first.")
            return

        new_budget = current_cost / (pct / 100.0)
        self.config.set_session_budget(new_budget)
        self._on_manual_refresh(None)
        rumps.notification(
            title="Calibrated",
            subtitle=f"Session budget: ${new_budget:.2f}",
            message=f"Based on {pct:.0f}% and ${current_cost:.2f} current cost",
        )
```

- [ ] **Step 2: Add menu item to subscription menu**

In `_update_subscription_menu`, add a "Calibrate..." item after the plan submenu (after line 586 in the current code, before `style_label`):

```python
        calibrate_item = rumps.MenuItem("Calibrate...", callback=self._on_calibrate)
        items.append(calibrate_item)
```

- [ ] **Step 3: Manual test — run the app and verify the menu item appears**

Run: `uv run python -m claude_monitor`
Expected: "Calibrate..." item appears in the menu between Plan submenu and Style toggle.

- [ ] **Step 4: Commit**

```bash
git add claude_monitor/app.py
git commit -m "feat: add Calibrate menu item for session budget alignment"
```

---

### Task 10: Run full test suite and cleanup

**Files:**
- All test files
- Verify: `claude_monitor/config.py` (PLAN_LIMITS still exists but unused for %)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All 261+ tests PASS. Fix any remaining failures from old field references.

- [ ] **Step 2: Search for any remaining references to old fields**

Check for stale references to `tokens_used`, `tokens_limit`, `tokens_remaining` on `ModelUsageStatus`, and `daily_limits` parameter:

```bash
uv run python -c "
import ast, sys
for f in ['claude_monitor/app.py', 'claude_monitor/cli.py', 'claude_monitor/log_parser.py', 'claude_monitor/extra_usage.py']:
    with open(f) as fh:
        for i, line in enumerate(fh, 1):
            for term in ['tokens_used', 'tokens_limit', 'tokens_remaining', 'daily_limits']:
                if term in line and not line.strip().startswith('#'):
                    print(f'{f}:{i}: {line.rstrip()}')
"
```

Expected: No matches in production code (only in comments or `PLAN_LIMITS` definition, which is kept for reference).

- [ ] **Step 3: Run CLI to verify final output**

Run: `uv run python -m claude_monitor.cli`
Expected: Percentages are now cost-based and match the session budget calibration.

- [ ] **Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "chore: cleanup stale token-based references"
```
