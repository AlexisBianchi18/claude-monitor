"""Reporte de costos de Claude Code en terminal."""

from __future__ import annotations

import argparse
from datetime import date

from .log_parser import ClaudeLogParser
from .models import DailyReport
from .pricing_fetcher import get_pricing_age, update_pricing


def _format_cost(cost: float) -> str:
    return f"${cost:,.4f}"


def _format_tokens(tokens: int) -> str:
    return f"{tokens:,}"


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

    parser = ClaudeLogParser()
    today = date.today()

    report = parser.get_daily_report(today)
    _print_daily_report(report)

    weekly = parser.get_weekly_report()
    _print_weekly_summary(weekly, today)

    # Fuente de precios
    age = get_pricing_age()
    if age:
        print(f"  Prices: {age}")
    else:
        print("  Prices: built-in defaults")


if __name__ == "__main__":
    main()
