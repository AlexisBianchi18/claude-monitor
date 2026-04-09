"""Dataclasses para el modelo de datos de Claude Code Cost Monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class TokenUsage:
    """Uso de tokens de una llamada a la API."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0  # total (5m + 1h)
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0

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
    models_used: set[str] = field(default_factory=set)


@dataclass
class RateLimitInfo:
    """Info de rate limit obtenida de los headers de respuesta de la API."""

    model: str
    tokens_limit: int
    tokens_remaining: int
    tokens_reset: datetime  # UTC-aware
    input_tokens_limit: int = 0
    input_tokens_remaining: int = 0
    output_tokens_limit: int = 0
    output_tokens_remaining: int = 0
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def usage_pct(self) -> float:
        """Porcentaje de tokens usados (0.0 a 100.0)."""
        if self.tokens_limit == 0:
            return 0.0
        used = self.tokens_limit - self.tokens_remaining
        return (used / self.tokens_limit) * 100.0

    @property
    def seconds_until_reset(self) -> int:
        """Segundos hasta que se reinicia el límite. 0 si ya pasó."""
        delta = self.tokens_reset - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))


@dataclass
class ApiCostReport:
    """Datos de costo obtenidos de la Admin API de Anthropic."""

    date: date
    total_cost_usd: float
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
