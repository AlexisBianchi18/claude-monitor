"""Dataclasses para el modelo de datos de Claude Code Cost Monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class TokenUsage:
    """Uso de tokens de una llamada a la API."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


@dataclass
class CostEntry:
    """Una entrada de costo individual (un mensaje assistant deduplicado)."""

    message_id: str
    model: str
    usage: TokenUsage
    cost_usd: float
    timestamp: datetime  # UTC-aware


@dataclass
class ProjectStats:
    """Estadísticas agregadas de un proyecto."""

    name: str  # último segmento del path (ej: "claude-monitor")
    display_name: str  # con desambiguación si hay colisión
    dir_name: str  # nombre codificado del directorio
    total_cost: float = 0.0
    total_tokens: int = 0
    entry_count: int = 0


@dataclass
class DailyReport:
    """Reporte de costos de un día."""

    date: date
    total_cost: float = 0.0
    total_tokens: int = 0
    entry_count: int = 0
    projects: list[ProjectStats] = field(default_factory=list)
