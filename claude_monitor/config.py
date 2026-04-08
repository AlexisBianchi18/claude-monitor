"""Configuración y tabla de precios para Claude Code Cost Monitor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CLAUDE_LOGS_DIR = Path.home() / ".claude" / "projects"

# --- Precios por modelo (USD por millón de tokens) ---


@dataclass(frozen=True)
class ModelPricing:
    """Precios de un modelo en USD por millón de tokens."""

    input: float
    output: float
    cache_read: float
    cache_create: float


PRICING_TABLE: dict[str, ModelPricing] = {
    # Opus 4.6
    "claude-opus-4-6": ModelPricing(15.0, 75.0, 1.50, 18.75),
    # Sonnet 4.6
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0, 0.30, 3.75),
    # Haiku 4.5
    "claude-haiku-4-5-20251001": ModelPricing(0.80, 4.0, 0.08, 1.0),
}

# Modelos a ignorar (no generan costo real)
SKIP_MODELS: set[str] = {"<synthetic>"}

# Solo contar entries de tipo "assistant"
BILLABLE_TYPE = "assistant"

# --- Constantes para la UI (Etapa 2+) ---
REFRESH_INTERVAL_SECONDS = 30
COST_ALERT_THRESHOLD_USD = 5.00
MAX_PROJECTS_IN_MENU = 10
CONFIG_DIR = Path.home() / ".claude-monitor"
