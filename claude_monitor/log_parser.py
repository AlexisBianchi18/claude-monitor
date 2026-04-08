"""Parser de logs JSONL de Claude Code."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from .config import BILLABLE_TYPE, CLAUDE_LOGS_DIR, PRICING_TABLE, SKIP_MODELS
from .models import CostEntry, DailyReport, ProjectStats, TokenUsage


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
        for entry in self.logs_dir.iterdir():
            if not entry.is_dir() or entry.name == "memory":
                continue
            stats = self._parse_project(entry, target_date)
            if stats.entry_count > 0:
                projects.append(stats)

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
        )

    def get_weekly_report(self) -> list[DailyReport]:
        """Retorna reportes de los últimos 7 días (de más antiguo a más reciente)."""
        from datetime import timedelta

        today = date.today()
        return [
            self.get_daily_report(today - timedelta(days=i)) for i in range(6, -1, -1)
        ]

    # --- Parsing interno ---

    def _parse_project(self, project_dir: Path, target_date: date) -> ProjectStats:
        """Parsea todos los archivos de sesión de un proyecto."""
        session_files = self._find_session_files(project_dir)
        name, display_name = self._extract_project_name(project_dir, session_files)

        all_entries: list[CostEntry] = []
        for f in session_files:
            all_entries.extend(self._parse_jsonl_file(f, target_date))

        return ProjectStats(
            name=name,
            display_name=display_name,
            dir_name=project_dir.name,
            total_cost=sum(e.cost_usd for e in all_entries),
            total_tokens=sum(e.usage.total_tokens for e in all_entries),
            entry_count=len(all_entries),
        )

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

                    usage = TokenUsage(
                        input_tokens=usage_raw.get("input_tokens", 0),
                        output_tokens=usage_raw.get("output_tokens", 0),
                        cache_read_input_tokens=usage_raw.get(
                            "cache_read_input_tokens", 0
                        ),
                        cache_creation_input_tokens=usage_raw.get(
                            "cache_creation_input_tokens", 0
                        ),
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
        pricing = PRICING_TABLE.get(model)
        if pricing is None:
            return 0.0

        return (
            usage.input_tokens * pricing.input
            + usage.output_tokens * pricing.output
            + usage.cache_read_input_tokens * pricing.cache_read
            + usage.cache_creation_input_tokens * pricing.cache_create
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
