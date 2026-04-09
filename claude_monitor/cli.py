"""Reporte de costos de Claude Code en terminal."""

from __future__ import annotations

import argparse
from datetime import date

from .config import ConfigManager
from .log_parser import ClaudeLogParser
from .models import DailyReport, PlanReport
from .pricing_fetcher import get_pricing_age, update_pricing


def _format_cost(cost: float) -> str:
    return f"${cost:,.4f}"


def _format_tokens(tokens: int) -> str:
    return f"{tokens:,}"


def _format_tokens_short(tokens: int) -> str:
    """Formatea tokens en formato corto: 2.1M, 500K, 42."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)


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


def _print_daily_report(report: DailyReport) -> None:
    date_str = report.date.strftime("%A, %B %d, %Y")
    header = f"  Claude Code Cost Report — {date_str}"

    print("=" * 60)
    print(header)
    print("=" * 60)
    print()
    print(f"  Today's total:  {_format_cost(report.total_cost)}")
    print(f"  Total tokens:   {_format_tokens(report.total_tokens)}")
    print(f"  API calls:      {report.entry_count}")
    print()

    if report.projects:
        print(f"  {'Project':<30} {'Cost':>10}  {'Calls':>7}")
        print(f"  {'-' * 30} {'-' * 10} {'-' * 7}")
        for p in report.projects:
            print(f"  {p.display_name:<30} {_format_cost(p.total_cost):>10}  {p.entry_count:>7}")
    else:
        print("  No API calls recorded today.")

    print()


def _print_weekly_summary(reports: list[DailyReport], today: date) -> None:
    print("  Last 7 days:")

    for r in reports:
        day_str = r.date.strftime("%a %m/%d")
        marker = " <-- today" if r.date == today else ""
        print(f"    {day_str}  {_format_cost(r.total_cost)}{marker}")

    week_total = sum(r.total_cost for r in reports)
    days_with_data = len(reports)
    avg = week_total / days_with_data if days_with_data > 0 else 0.0

    print(f"               {'--------':>10}")
    print(f"         Week  {_format_cost(week_total)}  (avg {_format_cost(avg)}/day)")
    print()


def _print_plan_report(report: PlanReport, style: str) -> None:
    plan_display = report.plan_name.replace("_", " ").title()
    print(f"  Plan: {plan_display}")
    print(f"  Overall usage: {report.overall_percentage:.1f}%")
    print()

    for m in report.models:
        short_name = m.model.replace("claude-", "").replace("-20251001", "")
        if style == "bar":
            bar = _render_bar(m.percentage)
            print(f"  {short_name:<20} {bar}  {m.percentage:.1f}%")
        else:
            used = _format_tokens_short(m.tokens_used)
            limit = _format_tokens_short(m.tokens_limit)
            print(f"  {short_name:<20} {used} / {limit}")

    print()
    reset_str = _format_reset_time(report.seconds_until_reset)
    print(f"  Reset: {reset_str}")
    print(f"  Equivalent API cost: ${report.equivalent_api_cost:.2f}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Claude Code cost report")
    ap.add_argument(
        "--update-prices",
        action="store_true",
        help="Fetch latest pricing from Anthropic docs",
    )
    args = ap.parse_args()

    if args.update_prices:
        print("Fetching latest pricing from Anthropic...")
        pricing, error = update_pricing()
        if error:
            print(f"Warning: {error}")
            print("Using fallback prices.")
        else:
            print(f"Prices updated: {len(pricing)} models")
        return

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


if __name__ == "__main__":
    main()
