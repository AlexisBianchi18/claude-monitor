"""Claude Code Cost Monitor — macOS Menu Bar App."""

from __future__ import annotations

from datetime import date

import rumps

from .config import (
    COST_ALERT_THRESHOLD_USD,
    MAX_PROJECTS_IN_MENU,
    REFRESH_INTERVAL_SECONDS,
)
from .log_parser import ClaudeLogParser
from .models import DailyReport


class ClaudeMonitorApp(rumps.App):
    """App de barra de menu que muestra el costo de Claude Code."""

    def __init__(self) -> None:
        super().__init__("C \u2026", quit_button=None)
        self.parser = ClaudeLogParser()

        # Items fijos del menu
        self._today_item = rumps.MenuItem("Today: loading...", callback=None)
        self._separator1 = rumps.separator
        # Project items se generan dinamicamente
        self._separator2 = rumps.separator
        self._week_item = rumps.MenuItem("This week: ...", callback=None)
        self._separator3 = rumps.separator
        self._refresh_item = rumps.MenuItem("Refresh Now", callback=self._on_refresh)
        self._separator4 = rumps.separator
        self._quit_item = rumps.MenuItem("Quit", callback=self._on_quit)

        self.menu = [
            self._today_item,
            self._separator1,
            self._separator2,
            self._week_item,
            self._separator3,
            self._refresh_item,
            self._separator4,
            self._quit_item,
        ]

        # Timer de auto-refresh
        self._timer = rumps.Timer(self._on_timer, REFRESH_INTERVAL_SECONDS)
        self._timer.start()

        # Refresh inmediato al arrancar
        self._refresh()

    # --- Callbacks ---

    def _on_timer(self, sender: rumps.Timer) -> None:
        self._refresh()

    def _on_refresh(self, sender: rumps.MenuItem | None = None) -> None:
        self._refresh()

    def _on_quit(self, sender: rumps.MenuItem) -> None:
        rumps.quit_application()

    # --- Logica de refresh ---

    def _refresh(self) -> None:
        try:
            today = date.today()
            report = self.parser.get_daily_report(today)
            weekly = self.parser.get_weekly_report()

            self._update_title(report)
            self._update_menu(report, weekly)
        except Exception:
            self.title = "C err"

    def _update_title(self, report: DailyReport) -> None:
        cost = report.total_cost
        if cost >= COST_ALERT_THRESHOLD_USD:
            self.title = f"\u26a0 ${cost:.2f}"
        else:
            self.title = f"C ${cost:.2f}"

    def _update_menu(
        self, report: DailyReport, weekly: list[DailyReport]
    ) -> None:
        # Today summary
        self._today_item.title = (
            f"Today: ${report.total_cost:.2f}  "
            f"({report.entry_count} calls, {report.total_tokens:,} tokens)"
        )

        # Limpiar project items anteriores (entre separator1 y separator2)
        # rumps no permite manipular posiciones facilmente,
        # asi que reconstruimos el menu completo
        project_items: list[rumps.MenuItem] = []
        for p in report.projects[:MAX_PROJECTS_IN_MENU]:
            item = rumps.MenuItem(
                f"  {p.display_name:<28} ${p.total_cost:.2f}",
                callback=None,
            )
            project_items.append(item)

        # Weekly summary
        week_total = sum(r.total_cost for r in weekly)
        avg = week_total / len(weekly) if weekly else 0.0
        self._week_item.title = (
            f"This week: ${week_total:.2f}  (avg ${avg:.2f}/day)"
        )

        # Reconstruir menu
        self.menu.clear()
        self.menu = [
            self._today_item,
            self._separator1,
            *project_items,
            self._separator2,
            self._week_item,
            self._separator3,
            self._refresh_item,
            self._separator4,
            self._quit_item,
        ]


def main() -> None:
    ClaudeMonitorApp().run()


if __name__ == "__main__":
    main()
