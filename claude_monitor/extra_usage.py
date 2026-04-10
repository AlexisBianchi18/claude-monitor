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
