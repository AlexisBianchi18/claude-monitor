# Subscription Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "subscription" usage mode so users on Claude Max/Pro plans see token consumption vs plan limits (with visual bars or text) instead of API cost in USD.

**Architecture:** A new `usage_mode` config property bifurcates the presentation layer. The parser gains a `tokens_by_model` breakdown on `DailyReport` and a new `get_plan_report()` method that compares usage against configurable plan limits. `app.py` renders either cost (api mode) or usage bars/text (subscription mode). The existing api mode remains untouched.

**Tech Stack:** Python 3.11+, rumps, pytest, dataclasses

---

### Task 1: Add new dataclasses to models.py

**Files:**
- Modify: `claude_monitor/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new dataclasses**

Add to `tests/test_models.py`:

```python
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
        assert report.overall_percentage == 40.0  # 8M used / 20M total

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestModelUsageStatus tests/test_models.py::TestPlanReport -v`
Expected: FAIL — `ModelUsageStatus` and `PlanReport` not defined

- [ ] **Step 3: Add dataclasses to models.py**

Add at the end of `claude_monitor/models.py`, after `ApiCostReport`:

```python
@dataclass
class ModelUsageStatus:
    """Estado de uso de un modelo en el periodo actual."""

    model: str
    tokens_used: int
    tokens_limit: int

    @property
    def percentage(self) -> float:
        """Porcentaje de tokens usados (0.0+). Puede ser >100 si excede el limite."""
        if self.tokens_limit <= 0:
            return 0.0
        return (self.tokens_used / self.tokens_limit) * 100.0

    @property
    def tokens_remaining(self) -> int:
        """Tokens restantes. 0 si se excedio el limite."""
        return max(0, self.tokens_limit - self.tokens_used)


@dataclass
class PlanReport:
    """Reporte de uso del plan de suscripcion."""

    plan_name: str
    models: list[ModelUsageStatus]
    estimated_reset: datetime | None
    equivalent_api_cost: float

    @property
    def overall_percentage(self) -> float:
        """Porcentaje global ponderado de uso."""
        total_used = sum(m.tokens_used for m in self.models)
        total_limit = sum(m.tokens_limit for m in self.models)
        if total_limit <= 0:
            return 0.0
        return (total_used / total_limit) * 100.0

    @property
    def seconds_until_reset(self) -> int:
        """Segundos hasta el proximo reset estimado. 0 si no hay estimacion."""
        if self.estimated_reset is None:
            return 0
        delta = self.estimated_reset - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
```

Also add the import `from datetime import timedelta` at the top of the file (it already imports `datetime` and `timezone`).

- [ ] **Step 4: Update the imports in test_models.py**

Add to the imports at the top of `tests/test_models.py`:

```python
from datetime import datetime, timedelta, timezone
from claude_monitor.models import ModelUsageStatus, PlanReport
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add claude_monitor/models.py tests/test_models.py
git commit -m "feat: add ModelUsageStatus and PlanReport dataclasses for subscription mode"
```

---

### Task 2: Add tokens_by_model to DailyReport

**Files:**
- Modify: `claude_monitor/models.py`
- Modify: `claude_monitor/log_parser.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Write test for tokens_by_model**

Add to `tests/test_parser.py` after `TestProjectOrdering`:

```python
class TestTokensByModel:
    def test_tokens_by_model_populated(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        assert isinstance(report.tokens_by_model, dict)
        assert len(report.tokens_by_model) > 0
        # La fixture tiene opus, sonnet y haiku
        assert "claude-opus-4-6" in report.tokens_by_model
        assert "claude-sonnet-4-6" in report.tokens_by_model
        assert "claude-haiku-4-5-20251001" in report.tokens_by_model

    def test_tokens_by_model_sums_correctly(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        # Total tokens should equal sum of per-model tokens
        model_total = sum(report.tokens_by_model.values())
        assert model_total == report.total_tokens

    def test_tokens_by_model_empty_when_no_data(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent/path"))
        report = parser.get_daily_report(TARGET_DATE)
        assert report.tokens_by_model == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parser.py::TestTokensByModel -v`
Expected: FAIL — `tokens_by_model` attribute not found on `DailyReport`

- [ ] **Step 3: Add tokens_by_model field to DailyReport**

In `claude_monitor/models.py`, add to the `DailyReport` dataclass:

```python
@dataclass
class DailyReport:
    """Reporte de costos de un dia."""

    date: date
    total_cost: float = 0.0
    total_tokens: int = 0
    entry_count: int = 0
    projects: list[ProjectStats] = field(default_factory=list)
    models_used: set[str] = field(default_factory=set)
    tokens_by_model: dict[str, int] = field(default_factory=dict)
```

- [ ] **Step 4: Update _parse_project to return per-model token data**

In `claude_monitor/log_parser.py`, change `_parse_project` to also compute and return `model_tokens`:

```python
def _parse_project(
    self, project_dir: Path, target_date: date
) -> tuple[ProjectStats, set[str], dict[str, int]]:
    """Parsea todos los archivos de sesion de un proyecto.

    Returns:
        (stats, models_used, model_tokens) where model_tokens maps
        model_id -> total tokens for that model in this project.
    """
    session_files = self._find_session_files(project_dir)
    name, display_name = self._extract_project_name(project_dir, session_files)

    all_entries: list[CostEntry] = []
    for f in session_files:
        all_entries.extend(self._parse_jsonl_file(f, target_date))

    models_used = {e.model for e in all_entries if e.model}

    model_tokens: dict[str, int] = {}
    for e in all_entries:
        model_tokens[e.model] = model_tokens.get(e.model, 0) + e.usage.total_tokens

    stats = ProjectStats(
        name=name,
        display_name=display_name,
        dir_name=project_dir.name,
        total_cost=sum(e.cost_usd for e in all_entries),
        total_tokens=sum(e.usage.total_tokens for e in all_entries),
        entry_count=len(all_entries),
    )
    return stats, models_used, model_tokens
```

- [ ] **Step 5: Update get_daily_report to merge tokens_by_model**

In `claude_monitor/log_parser.py`, update `get_daily_report`:

```python
def get_daily_report(self, target_date: date | None = None) -> DailyReport:
    """Genera un reporte de costos para un dia especifico (default: hoy)."""
    if target_date is None:
        target_date = date.today()

    if not self.logs_dir.is_dir():
        return DailyReport(date=target_date)

    projects: list[ProjectStats] = []
    all_models: set[str] = set()
    all_tokens_by_model: dict[str, int] = {}
    for entry in self.logs_dir.iterdir():
        if not entry.is_dir() or entry.name == "memory":
            continue
        stats, models, model_tokens = self._parse_project(entry, target_date)
        if stats.entry_count > 0:
            projects.append(stats)
            all_models.update(models)
            for model, tokens in model_tokens.items():
                all_tokens_by_model[model] = (
                    all_tokens_by_model.get(model, 0) + tokens
                )

    projects.sort(key=lambda p: p.total_cost, reverse=True)

    total_cost = sum(p.total_cost for p in projects)
    total_tokens = sum(p.total_tokens for p in projects)
    entry_count = sum(p.entry_count for p in projects)

    return DailyReport(
        date=target_date,
        total_cost=total_cost,
        total_tokens=total_tokens,
        entry_count=entry_count,
        projects=projects,
        models_used=all_models,
        tokens_by_model=all_tokens_by_model,
    )
```

- [ ] **Step 6: Run all parser tests**

Run: `uv run pytest tests/test_parser.py -v`
Expected: ALL PASS (including existing tests — the return type change is internal)

- [ ] **Step 7: Commit**

```bash
git add claude_monitor/models.py claude_monitor/log_parser.py tests/test_parser.py
git commit -m "feat: add tokens_by_model breakdown to DailyReport"
```

---

### Task 3: Add plan configuration to config.py

**Files:**
- Modify: `claude_monitor/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write tests for plan configuration**

Add to `tests/test_config.py`:

```python
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

    def test_reset_hour_utc_default(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        assert mgr.reset_hour_utc == 7

    def test_set_plan(self, config_path):
        mgr = ConfigManager(config_path=config_path)
        mgr.set_plan("max_20x")
        assert mgr.plan == "max_20x"
        # Verify it persisted
        mgr2 = ConfigManager(config_path=config_path)
        assert mgr2.plan == "max_20x"

    def test_unknown_plan_uses_custom(self, config_path):
        config_path.write_text(json.dumps({"plan": "nonexistent"}))
        mgr = ConfigManager(config_path=config_path)
        # Unknown plan returns empty limits
        limits = mgr.daily_token_limits
        assert limits == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py::TestPlanConfig -v`
Expected: FAIL — new properties not defined

- [ ] **Step 3: Add plan constants and PLAN_LIMITS table to config.py**

Add after `CONFIG_FILE` definition (around line 49) in `claude_monitor/config.py`:

```python
# --- Plan de suscripcion ---
VALID_USAGE_MODES = {"api", "subscription"}
VALID_DISPLAY_STYLES = {"bar", "text"}
DEFAULT_RESET_HOUR_UTC = 7  # ~midnight Chile

# Limites diarios estimados de tokens por plan (ajustables por el usuario)
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "pro": {
        "claude-opus-4-6": 2_000_000,
        "claude-sonnet-4-6": 10_000_000,
        "claude-haiku-4-5-20251001": 30_000_000,
    },
    "max_5x": {
        "claude-opus-4-6": 10_000_000,
        "claude-sonnet-4-6": 50_000_000,
        "claude-haiku-4-5-20251001": 150_000_000,
    },
    "max_20x": {
        "claude-opus-4-6": 40_000_000,
        "claude-sonnet-4-6": 200_000_000,
        "claude-haiku-4-5-20251001": 600_000_000,
    },
}
```

- [ ] **Step 4: Update ConfigManager defaults and add new properties**

Update `_defaults` in `ConfigManager`:

```python
_defaults: dict = {
    "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
    "cost_alert_threshold_usd": COST_ALERT_THRESHOLD_USD,
    "max_projects_in_menu": MAX_PROJECTS_IN_MENU,
    "anthropic_api_key": "",
    "usage_mode": "api",
    "plan": "max_5x",
    "display_style": "bar",
    "reset_hour_utc": DEFAULT_RESET_HOUR_UTC,
}
```

Add new properties after the `set_api_key` method:

```python
# --- Plan de suscripcion ---

@property
def usage_mode(self) -> str:
    """'api' o 'subscription'."""
    val = str(self._data.get("usage_mode", "api"))
    return val if val in VALID_USAGE_MODES else "api"

@property
def plan(self) -> str:
    return str(self._data.get("plan", "max_5x"))

@property
def display_style(self) -> str:
    """'bar' o 'text'."""
    val = str(self._data.get("display_style", "bar"))
    return val if val in VALID_DISPLAY_STYLES else "bar"

@property
def reset_hour_utc(self) -> int:
    return int(self._data.get("reset_hour_utc", DEFAULT_RESET_HOUR_UTC))

@property
def daily_token_limits(self) -> dict[str, int]:
    """Limites diarios por modelo. Custom overrides > plan defaults."""
    custom = self._data.get("daily_token_limits")
    if isinstance(custom, dict) and custom:
        return {k: int(v) for k, v in custom.items()}
    return dict(PLAN_LIMITS.get(self.plan, {}))

def set_plan(self, plan: str) -> None:
    """Cambia el plan y persiste. Limpia custom limits."""
    self._data["plan"] = plan
    self._data.pop("daily_token_limits", None)
    self.save()

def toggle_display_style(self) -> None:
    """Alterna entre 'bar' y 'text' y persiste."""
    current = self.display_style
    self._data["display_style"] = "text" if current == "bar" else "bar"
    self.save()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add claude_monitor/config.py tests/test_config.py
git commit -m "feat: add plan configuration (usage_mode, plan, display_style, token limits)"
```

---

### Task 4: Add get_plan_report to log_parser.py

**Files:**
- Modify: `claude_monitor/log_parser.py`
- Create: `tests/test_plan_report.py`

- [ ] **Step 1: Write tests for get_plan_report**

Create `tests/test_plan_report.py`:

```python
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
        # equivalent_api_cost should match DailyReport.total_cost
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
        """Only models present in daily_limits appear in the report."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plan_report.py -v`
Expected: FAIL — `get_plan_report` not defined

- [ ] **Step 3: Implement get_plan_report in log_parser.py**

Add this method to `ClaudeLogParser` after `get_weekly_report`, and add the import of `ModelUsageStatus, PlanReport` at the top:

Update the import line in `log_parser.py`:
```python
from .models import CostEntry, DailyReport, ModelUsageStatus, PlanReport, ProjectStats, TokenUsage
```

Add the method:

```python
def get_plan_report(
    self,
    plan_name: str,
    daily_limits: dict[str, int],
    reset_hour_utc: int = 7,
    target_date: date | None = None,
) -> PlanReport:
    """Genera un reporte de uso para modo suscripcion.

    Compara tokens usados hoy contra los limites configurados del plan.
    """
    daily = self.get_daily_report(target_date)

    models: list[ModelUsageStatus] = []
    for model, limit in sorted(daily_limits.items()):
        tokens_used = daily.tokens_by_model.get(model, 0)
        models.append(ModelUsageStatus(
            model=model,
            tokens_used=tokens_used,
            tokens_limit=limit,
        ))

    estimated_reset = self._estimate_next_reset(reset_hour_utc)

    return PlanReport(
        plan_name=plan_name,
        models=models,
        estimated_reset=estimated_reset,
        equivalent_api_cost=daily.total_cost,
    )

@staticmethod
def _estimate_next_reset(reset_hour_utc: int) -> datetime:
    """Calcula el proximo reset basado en la hora UTC configurada."""
    now = datetime.now(timezone.utc)
    today_reset = now.replace(
        hour=reset_hour_utc, minute=0, second=0, microsecond=0
    )
    if now >= today_reset:
        return today_reset + timedelta(days=1)
    return today_reset
```

Also add `timedelta` to the top-level import (move it from inside `get_weekly_report`):

```python
from datetime import date, datetime, timedelta, timezone
```

And remove the `from datetime import timedelta` line inside `get_weekly_report`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_plan_report.py tests/test_parser.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add claude_monitor/log_parser.py tests/test_plan_report.py
git commit -m "feat: add get_plan_report() for subscription mode token tracking"
```

---

### Task 5: Add subscription mode to app.py

**Files:**
- Modify: `claude_monitor/app.py`

- [ ] **Step 1: Add rendering helpers**

Add these functions at the top of `claude_monitor/app.py`, after imports and before the class:

```python
def _render_bar(percentage: float, width: int = 10) -> str:
    """Renderiza una barra de progreso con caracteres Unicode."""
    clamped = max(0.0, min(percentage, 100.0))
    filled = round(clamped / 100.0 * width)
    return "\u25b0" * filled + "\u25b1" * (width - filled)


def _format_tokens_short(tokens: int) -> str:
    """Formatea tokens en formato corto: 2.1M, 500K, 42."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)


def _format_reset_time(seconds: int) -> str:
    """Formatea segundos restantes en formato legible."""
    if seconds <= 0:
        return "now"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
```

- [ ] **Step 2: Add PlanReport import**

Update imports at the top of `app.py`:

```python
from .models import DailyReport, PlanReport, RateLimitInfo
```

- [ ] **Step 3: Add display style toggle to __init__**

In `__init__`, add a new menu item after `self._reset_item` and before `self._prefs_item`:

```python
self._style_item = rumps.MenuItem(
    "Style: Bars \u25b0\u25b0\u25b0", callback=self._on_toggle_style
)
```

- [ ] **Step 4: Add the toggle callback**

Add after `_on_configure_api_key`:

```python
def _on_toggle_style(self, sender: rumps.MenuItem) -> None:
    """Alterna entre estilo bar y text."""
    self.config.toggle_display_style()
    self._refresh()
```

- [ ] **Step 5: Modify _refresh to handle subscription mode**

Replace the `_refresh` method body:

```python
def _refresh(self) -> None:
    try:
        today = date.today()
        report = self.parser.get_daily_report(today)
        weekly = self.parser.get_weekly_report()

        # Guardar modelos usados hoy para polling en background
        self._last_models_used = sorted(report.models_used)

        if self.config.usage_mode == "subscription":
            self._refresh_subscription(today, report, weekly)
        else:
            self._refresh_api(today, report, weekly)
    except Exception:
        self.title = "C err"
```

- [ ] **Step 6: Extract current refresh logic into _refresh_api**

Move the existing refresh logic (without the try/except wrapper) into a new method:

```python
def _refresh_api(
    self, today: date, report: DailyReport, weekly: list[DailyReport]
) -> None:
    """Refresh en modo API (comportamiento original)."""
    offset = self.config.get_daily_offset(today)
    display_cost = max(0.0, report.total_cost - offset)

    rate_limits_map: dict[str, RateLimitInfo] = {}
    api_cost = None
    if self.config.has_api_key:
        rate_limits_map = get_rate_limits(
            self.config.api_key, self._last_models_used
        )
        if self.config.api_key_type == "admin":
            cost_report = get_cost_report(self.config.api_key, today)
            if cost_report is not None:
                api_cost = cost_report.total_cost_usd
                display_cost = max(0.0, api_cost - offset)

    self._update_title(display_cost, today, api_source=api_cost is not None)
    self._update_menu(
        report, weekly, display_cost, rate_limits_map, api_cost is not None
    )

    age = get_pricing_age()
    self._pricing_item.title = (
        f"Prices: {age}" if age else "Prices: built-in defaults"
    )
    self._update_api_status()
```

- [ ] **Step 7: Add _refresh_subscription method**

```python
def _refresh_subscription(
    self, today: date, report: DailyReport, weekly: list[DailyReport]
) -> None:
    """Refresh en modo suscripcion."""
    plan_report = self.parser.get_plan_report(
        plan_name=self.config.plan,
        daily_limits=self.config.daily_token_limits,
        reset_hour_utc=self.config.reset_hour_utc,
        target_date=today,
    )

    # Titulo
    pct = plan_report.overall_percentage
    if pct >= 95:
        self.title = f"\U0001f534 {pct:.0f}%"
    elif pct >= 80:
        self.title = f"\u26a0 {pct:.0f}%"
    else:
        self.title = f"C {pct:.0f}%"

    # Construir menu
    self._update_subscription_menu(plan_report, report, weekly)
```

- [ ] **Step 8: Add _update_subscription_menu method**

```python
def _update_subscription_menu(
    self,
    plan_report: PlanReport,
    report: DailyReport,
    weekly: list[DailyReport],
) -> None:
    """Construye el menu para modo suscripcion."""
    style = self.config.display_style
    reset_str = _format_reset_time(plan_report.seconds_until_reset)

    items: list = []

    # Today summary
    total_tokens_str = _format_tokens_short(report.total_tokens)
    equiv_str = f"${plan_report.equivalent_api_cost:.2f}"
    today_item = rumps.MenuItem(
        f"Today: {total_tokens_str} tokens (\u2248 {equiv_str} API)",
        callback=None,
    )
    items.append(today_item)
    items.append(rumps.separator)

    # Per-model usage
    for m in plan_report.models:
        short_name = m.model.replace("claude-", "").replace("-20251001", "")
        if style == "bar":
            bar = _render_bar(m.percentage)
            line = f"  {short_name:<16} {bar}  {m.percentage:.0f}%"
        else:
            used_str = _format_tokens_short(m.tokens_used)
            limit_str = _format_tokens_short(m.tokens_limit)
            line = f"  {short_name:<16} {used_str} / {limit_str}"
        items.append(rumps.MenuItem(line, callback=None))

    items.append(rumps.separator)

    # Reset timer
    items.append(rumps.MenuItem(
        f"Reset: \u21bb {reset_str}", callback=None
    ))
    items.append(rumps.separator)

    # Projects
    max_projects = self.config.max_projects
    for p in report.projects[:max_projects]:
        tok_str = _format_tokens_short(p.total_tokens)
        items.append(rumps.MenuItem(
            f"  {p.display_name:<28} {tok_str}",
            callback=None,
        ))

    items.append(rumps.separator)

    # Weekly summary
    week_tokens = sum(r.total_tokens for r in weekly)
    week_cost = sum(r.total_cost for r in weekly)
    items.append(rumps.MenuItem(
        f"Week: {_format_tokens_short(week_tokens)} tokens "
        f"(\u2248 ${week_cost:.2f} API)",
        callback=None,
    ))
    items.append(rumps.separator)

    # Plan info + actions
    plan_display = self.config.plan.replace("_", " ").title()
    items.append(rumps.MenuItem(f"Plan: {plan_display}", callback=None))

    style_label = "Bars \u25b0\u25b0\u25b0" if style == "bar" else "Text 0/0"
    self._style_item.title = f"Style: {style_label}"
    items.append(self._style_item)
    items.append(self._refresh_item)
    items.append(self._reset_item)
    items.append(self._prefs_item)
    items.append(rumps.separator)
    items.append(self._quit_item)

    self.menu.clear()
    self.menu = items
```

- [ ] **Step 9: Update _build_menu_items to include style item in api mode**

In `_build_menu_items`, add `self._style_item` before `self._prefs_item`:

```python
items.append(self._reset_item)
items.append(self._style_item)
items.append(self._prefs_item)
```

- [ ] **Step 10: Test manually**

Run: `uv run python -m claude_monitor`

Verify the app starts in api mode (default). Then edit `~/.claude-monitor/config.json` and set `"usage_mode": "subscription"`, click "Refresh Now", and verify the menu shows bars/text.

- [ ] **Step 11: Commit**

```bash
git add claude_monitor/app.py
git commit -m "feat: add subscription mode UI with bar/text display styles"
```

---

### Task 6: Add subscription mode to cli.py

**Files:**
- Modify: `claude_monitor/cli.py`

- [ ] **Step 1: Add subscription report formatter**

Add after `_print_weekly_summary`:

```python
def _render_bar(percentage: float, width: int = 10) -> str:
    """Renderiza una barra de progreso con caracteres Unicode."""
    clamped = max(0.0, min(percentage, 100.0))
    filled = round(clamped / 100.0 * width)
    return "\u25b0" * filled + "\u25b1" * (width - filled)


def _format_reset_time(seconds: int) -> str:
    """Formatea segundos restantes en formato legible."""
    if seconds <= 0:
        return "now"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _print_plan_report(report: PlanReport, style: str) -> None:
    plan_display = report.plan_name.replace("_", " ").title()
    print(f"  Plan: {plan_display}")
    print(f"  Overall usage: {report.overall_percentage:.1f}%")
    print()

    for m in report.models:
        short_name = m.model.replace("claude-", "").replace("-20251001", "")
        if style == "bar":
            bar = _render_bar(m.percentage)
            print(f"  {short_name:<20} {bar}  {m.percentage:.0f}%")
        else:
            used = _format_tokens_short(m.tokens_used)
            limit = _format_tokens_short(m.tokens_limit)
            print(f"  {short_name:<20} {used} / {limit}")

    print()
    reset_str = _format_reset_time(report.seconds_until_reset)
    print(f"  Reset: {reset_str}")
    print(f"  Equivalent API cost: ${report.equivalent_api_cost:.2f}")
    print()
```

- [ ] **Step 2: Update main() to handle subscription mode**

Update the imports at the top of `cli.py`:

```python
from .config import ConfigManager
from .log_parser import ClaudeLogParser
from .models import DailyReport, PlanReport
from .pricing_fetcher import get_pricing_age, update_pricing
```

Replace the body of `main()` after the `--update-prices` block:

```python
config = ConfigManager()
parser = ClaudeLogParser()
today = date.today()

if config.usage_mode == "subscription":
    report = parser.get_plan_report(
        plan_name=config.plan,
        daily_limits=config.daily_token_limits,
        reset_hour_utc=config.reset_hour_utc,
        target_date=today,
    )

    print("=" * 60)
    print(f"  Claude Code Usage Report — {today.strftime('%A, %B %d, %Y')}")
    print("=" * 60)
    print()
    _print_plan_report(report, config.display_style)

    weekly = parser.get_weekly_report()
    week_tokens = sum(r.total_tokens for r in weekly)
    print(f"  This week: {_format_tokens_short(week_tokens)} tokens")
    print()
else:
    report = parser.get_daily_report(today)
    _print_daily_report(report)

    weekly = parser.get_weekly_report()
    _print_weekly_summary(weekly, today)

    age = get_pricing_age()
    if age:
        print(f"  Prices: {age}")
    else:
        print("  Prices: built-in defaults")
```

- [ ] **Step 3: Test manually**

Run: `uv run python -m claude_monitor.cli`

Verify it shows the current mode's output.

- [ ] **Step 4: Commit**

```bash
git add claude_monitor/cli.py
git commit -m "feat: add subscription mode to CLI report"
```

---

### Task 7: Run all tests and verify

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Fix any failures**

If any existing tests break, fix them. The most likely issue is tests that destructure `_parse_project`'s return value — those should now expect 3 values instead of 2. However, since `_parse_project` is only called internally by `get_daily_report` and tests don't call it directly (except `TestDeduplication` and `TestMissingUsage` which use `_parse_jsonl_file`), this should not be an issue.

- [ ] **Step 3: Commit any fixes**

```bash
git add -u
git commit -m "fix: resolve test failures from subscription mode changes"
```

---

### Task 8: Final integration test

- [ ] **Step 1: Run the app in subscription mode**

Edit `~/.claude-monitor/config.json`:

```json
{
  "usage_mode": "subscription",
  "plan": "max_5x",
  "display_style": "bar"
}
```

Run: `uv run python -m claude_monitor`

- [ ] **Step 2: Verify menu shows**

- Title: `C XX%` with percentage
- Per-model bars: `opus-4-6  ▰▰▱▱▱▱▱▱▱▱  XX%`
- Reset timer: `Reset: ↻ Xh Xm`
- Projects with token counts
- Style toggle works (click changes bar ↔ text)

- [ ] **Step 3: Verify CLI shows subscription output**

Run: `uv run python -m claude_monitor.cli`

- [ ] **Step 4: Switch back to api mode and verify no regression**

Edit config to `"usage_mode": "api"` and verify original behavior.

- [ ] **Step 5: Final commit if any adjustments needed**

```bash
git add -u
git commit -m "chore: final adjustments after integration testing"
```
