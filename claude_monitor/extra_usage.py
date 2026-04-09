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

    total_used = sum(m.tokens_used for m in plan_report.models)
    total_limit = sum(m.tokens_limit for m in plan_report.models)
    extra_tokens = max(0, total_used - total_limit)

    if total_used > 0:
        # Proporcion: el costo extra es la fraccion de tokens que exceden
        # el limite, aplicada al costo API total. Valido porque ambos
        # valores comparten el mismo mix de modelos y ventana de tiempo.
        extra_cost = (extra_tokens / total_used) * plan_report.equivalent_api_cost
    else:
        extra_cost = 0.0

    return ExtraUsageStatus(
        limit_usd=extra_limit_usd,
        cost_usd=extra_cost,
        alert_threshold_pct=alert_threshold_pct,
    )
