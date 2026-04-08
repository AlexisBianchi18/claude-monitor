"""Claude Code Cost Monitor — macOS Menu Bar App."""

from __future__ import annotations

import os
from datetime import date

import rumps

from .config import ConfigManager
from .log_parser import ClaudeLogParser
from .models import DailyReport


class ClaudeMonitorApp(rumps.App):
    """App de barra de menu que muestra el costo de Claude Code."""

    def __init__(self) -> None:
        super().__init__("C \u2026", quit_button=None)
        self.parser = ClaudeLogParser()
        self.config = ConfigManager()

        # Items fijos del menu
        self._today_item = rumps.MenuItem("Today: loading...", callback=None)
        self._separator1 = rumps.separator
        # Project items se generan dinamicamente
        self._separator2 = rumps.separator
        self._week_item = rumps.MenuItem("This week: ...", callback=None)
        self._separator3 = rumps.separator
        self._refresh_item = rumps.MenuItem("Refresh Now", callback=self._on_refresh)
        self._reset_item = rumps.MenuItem(
            "Reset Daily Counter", callback=self._on_reset_daily
        )
        self._prefs_item = rumps.MenuItem(
            "Preferences\u2026", callback=self._on_open_prefs
        )
        self._separator4 = rumps.separator
        self._quit_item = rumps.MenuItem("Quit", callback=self._on_quit)

        self.menu = [
            self._today_item,
            self._separator1,
            self._separator2,
            self._week_item,
            self._separator3,
            self._refresh_item,
            self._reset_item,
            self._prefs_item,
            self._separator4,
            self._quit_item,
        ]

        # Timer de auto-refresh
        self._timer = rumps.Timer(self._on_timer, self.config.refresh_interval)
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

    def _on_reset_daily(self, sender: rumps.MenuItem) -> None:
        """Resetea el contador diario guardando el costo actual como offset."""
        response = rumps.alert(
            title="Reset Daily Counter",
            message="This will reset today's cost display to $0.00. Continue?",
            ok="Reset",
            cancel="Cancel",
        )
        if response == 1:  # OK pressed
            today = date.today()
            report = self.parser.get_daily_report(today)
            self.config.set_daily_offset(today, report.total_cost)
            self._refresh()

    def _on_open_prefs(self, sender: rumps.MenuItem) -> None:
        """Abre el archivo de configuración con el editor del sistema."""
        # Asegurar que el archivo existe antes de abrirlo
        if not self.config.config_path.is_file():
            self.config.save()
        os.system(f'open -e "{self.config.config_path}"')

    # --- Logica de refresh ---

    def _refresh(self) -> None:
        try:
            today = date.today()
            report = self.parser.get_daily_report(today)
            weekly = self.parser.get_weekly_report()

            # Aplicar offset de reset diario
            offset = self.config.get_daily_offset(today)
            display_cost = max(0.0, report.total_cost - offset)

            self._update_title(display_cost, today)
            self._update_menu(report, weekly, display_cost)
        except Exception:
            self.title = "C err"

    def _update_title(self, display_cost: float, today: date) -> None:
        threshold = self.config.alert_threshold
        if display_cost >= threshold:
            self.title = f"\u26a0 ${display_cost:.2f}"
            # Enviar notificación una vez por día
            if not self.config.has_alert_fired_today(today):
                self.config.mark_alert_fired(today)
                rumps.notification(
                    title="Claude Code Cost Alert",
                    subtitle=f"Daily cost exceeded ${threshold:.2f}",
                    message=f"Current cost: ${display_cost:.2f}",
                )
        else:
            self.title = f"C ${display_cost:.2f}"

    def _update_menu(
        self,
        report: DailyReport,
        weekly: list[DailyReport],
        display_cost: float,
    ) -> None:
        # Today summary (muestra display_cost con offset aplicado)
        self._today_item.title = (
            f"Today: ${display_cost:.2f}  "
            f"({report.entry_count} calls, {report.total_tokens:,} tokens)"
        )

        # Project items
        max_projects = self.config.max_projects
        project_items: list[rumps.MenuItem] = []
        for p in report.projects[:max_projects]:
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
            self._reset_item,
            self._prefs_item,
            self._separator4,
            self._quit_item,
        ]


def main() -> None:
    ClaudeMonitorApp().run()


if __name__ == "__main__":
    main()
