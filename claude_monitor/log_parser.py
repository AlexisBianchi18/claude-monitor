"""Parser de logs JSONL de Claude Code."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import BILLABLE_TYPE, CLAUDE_LOGS_DIR, SKIP_MODELS
from .pricing_fetcher import get_pricing_table
from .models import CostEntry, DailyReport, ModelUsageStatus, PlanReport, ProjectStats, TokenUsage


class ClaudeLogParser:
    """Lee y parsea los logs locales de Claude Code en ~/.claude/projects/."""

    def __init__(self, logs_dir: Path | None = None) -> None:
        self.logs_dir = logs_dir or CLAUDE_LOGS_DIR

    # --- API pública ---

    def get_daily_report(self, target_date: date | None = None) -> DailyReport:
        """Genera un reporte de costos para un día específico (default: hoy)."""
        if target_date is None:
            target_date = date.today()

        if not self.logs_dir.is_dir():
            return DailyReport(date=target_date)

        projects: list[ProjectStats] = []
        all_models: set[str] = set()
        all_tokens_by_model: dict[str, int] = {}
        all_effective_tokens_by_model: dict[str, int] = {}
        all_cost_by_model: dict[str, float] = {}
        for entry in self.logs_dir.iterdir():
            if not entry.is_dir() or entry.name == "memory":
                continue
            stats, models, model_tokens, eff_model_tokens, cost_model = self._parse_project(
                entry, target_date
            )
            if stats.entry_count > 0:
                projects.append(stats)
                all_models.update(models)
                for model, tokens in model_tokens.items():
                    all_tokens_by_model[model] = (
                        all_tokens_by_model.get(model, 0) + tokens
                    )
                for model, tokens in eff_model_tokens.items():
                    all_effective_tokens_by_model[model] = (
                        all_effective_tokens_by_model.get(model, 0) + tokens
                    )
                for model, cost in cost_model.items():
                    all_cost_by_model[model] = (
                        all_cost_by_model.get(model, 0.0) + cost
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
            effective_tokens_by_model=all_effective_tokens_by_model,
            cost_by_model=all_cost_by_model,
        )

    def get_weekly_report(self) -> list[DailyReport]:
        """Retorna reportes de los últimos 7 días (de más antiguo a más reciente)."""
        today = date.today()
        return [
            self.get_daily_report(today - timedelta(days=i)) for i in range(6, -1, -1)
        ]

    def get_window_report(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> DailyReport:
        """Genera un reporte de uso filtrando por ventana de tiempo (UTC)."""
        if not self.logs_dir.is_dir():
            return DailyReport(date=window_start.date())

        projects: list[ProjectStats] = []
        all_models: set[str] = set()
        all_tokens_by_model: dict[str, int] = {}
        all_effective_tokens_by_model: dict[str, int] = {}
        all_cost_by_model: dict[str, float] = {}

        for entry in self.logs_dir.iterdir():
            if not entry.is_dir() or entry.name == "memory":
                continue
            stats, models, model_tokens, eff_model_tokens, cost_model = (
                self._parse_project_window(entry, window_start, window_end)
            )
            if stats.entry_count > 0:
                projects.append(stats)
                all_models.update(models)
                for model, tokens in model_tokens.items():
                    all_tokens_by_model[model] = (
                        all_tokens_by_model.get(model, 0) + tokens
                    )
                for model, tokens in eff_model_tokens.items():
                    all_effective_tokens_by_model[model] = (
                        all_effective_tokens_by_model.get(model, 0) + tokens
                    )
                for model, cost in cost_model.items():
                    all_cost_by_model[model] = (
                        all_cost_by_model.get(model, 0.0) + cost
                    )

        projects.sort(key=lambda p: p.total_cost, reverse=True)
        total_cost = sum(p.total_cost for p in projects)
        total_tokens = sum(p.total_tokens for p in projects)
        entry_count = sum(p.entry_count for p in projects)

        return DailyReport(
            date=window_start.date(),
            total_cost=total_cost,
            total_tokens=total_tokens,
            entry_count=entry_count,
            projects=projects,
            models_used=all_models,
            tokens_by_model=all_tokens_by_model,
            effective_tokens_by_model=all_effective_tokens_by_model,
            cost_by_model=all_cost_by_model,
        )

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

    @staticmethod
    def _compute_window_boundaries(
        anchor: datetime, window_hours: int = 5, *, _now: datetime | None = None
    ) -> tuple[datetime, datetime]:
        """Calcula inicio y fin de la ventana actual basada en un anchor y ciclo."""
        now = _now or datetime.now(timezone.utc)
        window_secs = window_hours * 3600
        delta = (now - anchor).total_seconds()
        cycles = int(delta // window_secs)
        window_start = anchor + timedelta(seconds=cycles * window_secs)
        window_end = window_start + timedelta(hours=window_hours)
        return window_start, window_end

    @staticmethod
    def _estimate_next_reset(
        anchor: datetime | None, window_hours: int = 5, *, _now: datetime | None = None
    ) -> datetime | None:
        """Calcula el próximo reset basado en anchor y ventana."""
        if anchor is None:
            return None
        _, window_end = ClaudeLogParser._compute_window_boundaries(
            anchor, window_hours, _now=_now
        )
        return window_end

    # --- Parsing interno ---

    def _parse_project(
        self, project_dir: Path, target_date: date
    ) -> tuple[ProjectStats, set[str], dict[str, int], dict[str, int], dict[str, float]]:
        """Parsea todos los archivos de sesion de un proyecto.

        Returns:
            (stats, models_used, model_tokens, effective_model_tokens, cost_by_model)
        """
        session_files = self._find_session_files(project_dir)
        name, display_name = self._extract_project_name(project_dir, session_files)

        all_entries: list[CostEntry] = []
        for f in session_files:
            all_entries.extend(self._parse_jsonl_file(f, target_date))

        models_used = {e.model for e in all_entries if e.model}

        model_tokens: dict[str, int] = {}
        effective_model_tokens: dict[str, int] = {}
        for e in all_entries:
            model_tokens[e.model] = model_tokens.get(e.model, 0) + e.usage.total_tokens
            effective_model_tokens[e.model] = (
                effective_model_tokens.get(e.model, 0) + e.usage.effective_tokens
            )

        cost_by_model: dict[str, float] = {}
        for e in all_entries:
            cost_by_model[e.model] = cost_by_model.get(e.model, 0.0) + e.cost_usd

        stats = ProjectStats(
            name=name,
            display_name=display_name,
            dir_name=project_dir.name,
            total_cost=sum(e.cost_usd for e in all_entries),
            total_tokens=sum(e.usage.total_tokens for e in all_entries),
            entry_count=len(all_entries),
        )
        return stats, models_used, model_tokens, effective_model_tokens, cost_by_model

    def _parse_jsonl_file(
        self, path: Path, target_date: date
    ) -> list[CostEntry]:
        """Parsea un archivo JSONL con deduplicación por message.id."""
        entries_by_id: dict[str, CostEntry] = {}

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    if obj.get("type") != BILLABLE_TYPE:
                        continue

                    message = obj.get("message")
                    if not isinstance(message, dict):
                        continue

                    usage_raw = message.get("usage")
                    if not isinstance(usage_raw, dict):
                        continue

                    model = message.get("model", "")
                    if model in SKIP_MODELS:
                        continue

                    message_id = message.get("id", "")
                    if not message_id:
                        continue

                    ts_str = obj.get("timestamp", "")
                    ts = self._parse_timestamp(ts_str)
                    if ts is None:
                        continue

                    local_date = self._timestamp_to_local_date(ts)
                    if local_date != target_date:
                        continue

                    cache_creation_total = usage_raw.get(
                        "cache_creation_input_tokens", 0
                    )
                    cache_detail = usage_raw.get("cache_creation", {})
                    cache_1h = 0
                    cache_5m = 0
                    if isinstance(cache_detail, dict):
                        cache_1h = cache_detail.get(
                            "ephemeral_1h_input_tokens", 0
                        )
                        cache_5m = cache_detail.get(
                            "ephemeral_5m_input_tokens", 0
                        )
                    # Fallback: si no hay desglose, tratar todo como 5m
                    if cache_creation_total > 0 and (cache_1h + cache_5m) == 0:
                        cache_5m = cache_creation_total

                    usage = TokenUsage(
                        input_tokens=usage_raw.get("input_tokens", 0),
                        output_tokens=usage_raw.get("output_tokens", 0),
                        cache_read_input_tokens=usage_raw.get(
                            "cache_read_input_tokens", 0
                        ),
                        cache_creation_input_tokens=cache_creation_total,
                        cache_creation_5m_tokens=cache_5m,
                        cache_creation_1h_tokens=cache_1h,
                    )

                    cost = self._calculate_cost(model, usage)

                    # Deduplicación: el último entry con el mismo id gana
                    entries_by_id[message_id] = CostEntry(
                        message_id=message_id,
                        model=model,
                        usage=usage,
                        cost_usd=cost,
                        timestamp=ts,
                    )
        except OSError:
            return []

        return list(entries_by_id.values())

    def _parse_project_window(
        self, project_dir: Path, window_start: datetime, window_end: datetime
    ) -> tuple[ProjectStats, set[str], dict[str, int], dict[str, int], dict[str, float]]:
        """Parsea un proyecto filtrando por ventana de tiempo."""
        session_files = self._find_session_files(project_dir)
        name, display_name = self._extract_project_name(project_dir, session_files)

        all_entries: list[CostEntry] = []
        for f in session_files:
            all_entries.extend(self._parse_jsonl_file_window(f, window_start, window_end))

        models_used = {e.model for e in all_entries if e.model}
        model_tokens: dict[str, int] = {}
        effective_model_tokens: dict[str, int] = {}
        for e in all_entries:
            model_tokens[e.model] = model_tokens.get(e.model, 0) + e.usage.total_tokens
            effective_model_tokens[e.model] = (
                effective_model_tokens.get(e.model, 0) + e.usage.effective_tokens
            )

        cost_by_model: dict[str, float] = {}
        for e in all_entries:
            cost_by_model[e.model] = cost_by_model.get(e.model, 0.0) + e.cost_usd

        stats = ProjectStats(
            name=name, display_name=display_name, dir_name=project_dir.name,
            total_cost=sum(e.cost_usd for e in all_entries),
            total_tokens=sum(e.usage.total_tokens for e in all_entries),
            entry_count=len(all_entries),
        )
        return stats, models_used, model_tokens, effective_model_tokens, cost_by_model

    def _parse_jsonl_file_window(
        self, path: Path, window_start: datetime, window_end: datetime
    ) -> list[CostEntry]:
        """Parsea un archivo JSONL filtrando por ventana de tiempo UTC."""
        entries_by_id: dict[str, CostEntry] = {}
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    if obj.get("type") != BILLABLE_TYPE:
                        continue
                    message = obj.get("message")
                    if not isinstance(message, dict):
                        continue
                    usage_raw = message.get("usage")
                    if not isinstance(usage_raw, dict):
                        continue
                    model = message.get("model", "")
                    if model in SKIP_MODELS:
                        continue
                    message_id = message.get("id", "")
                    if not message_id:
                        continue

                    ts_str = obj.get("timestamp", "")
                    ts = self._parse_timestamp(ts_str)
                    if ts is None:
                        continue

                    if ts < window_start or ts >= window_end:
                        continue

                    cache_creation_total = usage_raw.get(
                        "cache_creation_input_tokens", 0
                    )
                    cache_detail = usage_raw.get("cache_creation", {})
                    cache_1h = 0
                    cache_5m = 0
                    if isinstance(cache_detail, dict):
                        cache_1h = cache_detail.get(
                            "ephemeral_1h_input_tokens", 0
                        )
                        cache_5m = cache_detail.get(
                            "ephemeral_5m_input_tokens", 0
                        )
                    if cache_creation_total > 0 and (cache_1h + cache_5m) == 0:
                        cache_5m = cache_creation_total

                    usage = TokenUsage(
                        input_tokens=usage_raw.get("input_tokens", 0),
                        output_tokens=usage_raw.get("output_tokens", 0),
                        cache_read_input_tokens=usage_raw.get(
                            "cache_read_input_tokens", 0
                        ),
                        cache_creation_input_tokens=cache_creation_total,
                        cache_creation_5m_tokens=cache_5m,
                        cache_creation_1h_tokens=cache_1h,
                    )
                    cost = self._calculate_cost(model, usage)
                    entries_by_id[message_id] = CostEntry(
                        message_id=message_id, model=model,
                        usage=usage, cost_usd=cost, timestamp=ts,
                    )
        except OSError:
            return []
        return list(entries_by_id.values())

    def _find_session_files(self, project_dir: Path) -> list[Path]:
        """Busca archivos .jsonl de sesiones y subagentes."""
        files: list[Path] = []

        try:
            for item in project_dir.iterdir():
                if item.suffix == ".jsonl" and item.is_file():
                    files.append(item)
                elif item.is_dir() and item.name != "memory":
                    # Buscar subagentes: <session-uuid>/subagents/*.jsonl
                    subagents_dir = item / "subagents"
                    if subagents_dir.is_dir():
                        for sub_file in subagents_dir.iterdir():
                            if sub_file.suffix == ".jsonl" and sub_file.is_file():
                                files.append(sub_file)
        except OSError:
            pass

        return files

    def _extract_project_name(
        self, project_dir: Path, session_files: list[Path]
    ) -> tuple[str, str]:
        """Extrae el nombre del proyecto desde el campo cwd de los logs.

        Returns:
            (name, display_name) — name es el último segmento del path real,
            display_name es igual por ahora (desambiguación en futuras etapas).
        """
        for f in session_files:
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if obj.get("type") == "user" and obj.get("cwd"):
                            name = os.path.basename(obj["cwd"])
                            if name:
                                return name, name
            except OSError:
                continue

        # Fallback: usar el nombre codificado del directorio
        fallback = project_dir.name
        return fallback, fallback

    # --- Utilidades estáticas ---

    @staticmethod
    def _calculate_cost(model: str, usage: TokenUsage) -> float:
        """Calcula el costo en USD basándose en tokens y precios del modelo."""
        pricing = get_pricing_table().get(model)
        if pricing is None:
            return 0.0

        return (
            usage.input_tokens * pricing.input
            + usage.output_tokens * pricing.output
            + usage.cache_read_input_tokens * pricing.cache_read
            + usage.cache_creation_5m_tokens * pricing.cache_create_5m
            + usage.cache_creation_1h_tokens * pricing.cache_create_1h
        ) / 1_000_000

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime | None:
        """Parsea un timestamp ISO 8601 con Z a datetime UTC-aware."""
        if not ts_str:
            return None
        try:
            # Python 3.11+ fromisoformat soporta Z directamente,
            # pero por compatibilidad reemplazamos
            normalized = ts_str.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _timestamp_to_local_date(dt: datetime) -> date:
        """Convierte un datetime UTC-aware a fecha en zona horaria local."""
        local_dt = dt.astimezone()
        return local_dt.date()
