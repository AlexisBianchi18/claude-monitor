"""Claude Code Cost Monitor — macOS Menu Bar App."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date

import rumps

from .api_client import get_cost_report, get_last_error, get_rate_limits, invalidate_key
from .config import ConfigManager
from .log_parser import ClaudeLogParser
from .models import DailyReport, RateLimitInfo
from .pricing_fetcher import get_pricing_age, should_fetch, update_pricing

logger = logging.getLogger(__name__)


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
        self._pricing_item = rumps.MenuItem("Prices: built-in defaults", callback=None)
        self._api_status_item = rumps.MenuItem("API: not configured", callback=None)
        self._update_prices_item = rumps.MenuItem(
            "Update Prices Now", callback=self._on_update_prices
        )
        self._refresh_item = rumps.MenuItem("Refresh Now", callback=self._on_refresh)
        self._configure_api_item = rumps.MenuItem(
            "Configure API Key\u2026", callback=self._on_configure_api_key
        )
        self._reset_item = rumps.MenuItem(
            "Reset Daily Counter", callback=self._on_reset_daily
        )
        self._prefs_item = rumps.MenuItem(
            "Preferences\u2026", callback=self._on_open_prefs
        )
        self._separator4 = rumps.separator
        self._quit_item = rumps.MenuItem("Quit", callback=self._on_quit)

        self._last_models_used: list[str] = []

        self.menu = self._build_menu_items()

        # Timer de auto-refresh
        self._timer = rumps.Timer(self._on_timer, self.config.refresh_interval)
        self._timer.start()

        # Refresh inmediato al arrancar
        self._refresh()

        # Intentar actualizar precios en background al iniciar
        self._maybe_fetch_pricing()

    # --- Callbacks ---

    def _on_timer(self, sender: rumps.Timer) -> None:
        self._refresh()
        self._maybe_fetch_pricing()
        self._maybe_poll_api()

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

    def _on_configure_api_key(self, sender: rumps.MenuItem) -> None:
        """Muestra un diálogo para ingresar/cambiar la API key."""
        current = self.config.api_key
        masked = self._mask_key(current) if current else ""
        response = rumps.Window(
            title="Anthropic API Key",
            message=(
                "Enter your API key (sk-ant-...) or leave empty to disable.\n"
                "Standard keys show rate limits. Admin keys also show real costs."
            ),
            default_text=masked,
            ok="Save",
            cancel="Cancel",
            dimensions=(420, 24),
        ).run()
        if response.clicked == 1:  # OK
            new_key = response.text.strip()
            # Si no cambió el texto enmascarado, no hacer nada
            if new_key == masked:
                return
            self.config.set_api_key(new_key)
            invalidate_key()
            self._refresh()

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key or len(key) < 14:
            return key
        return key[:10] + "..." + key[-4:]

    def _maybe_poll_api(self) -> None:
        """Lanza polling de API en background si hay key configurada."""
        if not self.config.has_api_key:
            return
        thread = threading.Thread(target=self._poll_api_background, daemon=True)
        thread.start()

    def _poll_api_background(self) -> None:
        """Fetch de rate limits y cost report en background."""
        key = self.config.api_key
        get_rate_limits(key, self._last_models_used)
        if self.config.api_key_type == "admin":
            get_cost_report(key, date.today())

    def _on_update_prices(self, sender: rumps.MenuItem) -> None:
        """Actualización manual de precios desde la web."""
        self._pricing_item.title = "Prices: updating..."
        thread = threading.Thread(
            target=self._fetch_pricing_background, daemon=True
        )
        thread.start()

    def _maybe_fetch_pricing(self) -> None:
        """Lanza fetch en background si el cache tiene más de 24h."""
        if not should_fetch():
            return
        thread = threading.Thread(
            target=self._fetch_pricing_background, daemon=True
        )
        thread.start()

    def _fetch_pricing_background(self) -> None:
        """Ejecuta fetch en un thread. El próximo _refresh() actualiza la UI."""
        _, error = update_pricing()
        if error:
            logger.warning("Price update failed: %s", error)

    # --- Logica de refresh ---

    def _refresh(self) -> None:
        try:
            today = date.today()
            report = self.parser.get_daily_report(today)
            weekly = self.parser.get_weekly_report()

            # Aplicar offset de reset diario
            offset = self.config.get_daily_offset(today)
            display_cost = max(0.0, report.total_cost - offset)

            # Guardar modelos usados hoy para polling en background
            self._last_models_used = sorted(report.models_used)

            # Integración API
            rate_limits_map: dict[str, RateLimitInfo] = {}
            api_cost = None
            if self.config.has_api_key:
                rate_limits_map = get_rate_limits(
                    self.config.api_key, self._last_models_used
                )
                if self.config.api_key_type == "admin":
                    cost_report = get_cost_report(self.config.api_key, today)
                    if cost_report is not None:
                        api_cost = cost_report.total_cost_usd
                        display_cost = max(0.0, api_cost - offset)

            self._update_title(display_cost, today, api_source=api_cost is not None)
            self._update_menu(
                report, weekly, display_cost, rate_limits_map, api_cost is not None
            )

            # Actualizar estado de precios y API
            age = get_pricing_age()
            self._pricing_item.title = (
                f"Prices: {age}" if age else "Prices: built-in defaults"
            )
            self._update_api_status()
        except Exception:
            self.title = "C err"

    def _update_title(
        self, display_cost: float, today: date, *, api_source: bool = False
    ) -> None:
        threshold = self.config.alert_threshold
        suffix = " \u2713" if api_source else ""
        if display_cost >= threshold:
            self.title = f"\u26a0 ${display_cost:.2f}{suffix}"
            # Enviar notificación una vez por día
            if not self.config.has_alert_fired_today(today):
                self.config.mark_alert_fired(today)
                rumps.notification(
                    title="Claude Code Cost Alert",
                    subtitle=f"Daily cost exceeded ${threshold:.2f}",
                    message=f"Current cost: ${display_cost:.2f}",
                )
        else:
            self.title = f"C ${display_cost:.2f}{suffix}"

    def _update_api_status(self) -> None:
        if not self.config.has_api_key:
            self._api_status_item.title = "API: not configured"
            return
        error = get_last_error()
        if error:
            self._api_status_item.title = f"API: {error}"
        else:
            key_type = self.config.api_key_type
            self._api_status_item.title = f"API: connected ({key_type})"

    @staticmethod
    def _format_rate_limit(info: RateLimitInfo) -> str:
        pct = info.usage_pct
        secs = info.seconds_until_reset
        if secs > 60:
            time_str = f"{secs // 60}m {secs % 60}s"
        else:
            time_str = f"{secs}s"
        # Nombre corto del modelo (ej: "claude-opus-4-6" → "opus-4-6")
        short_name = info.model.replace("claude-", "")
        return f"{short_name}: {pct:.0f}% used \u00b7 resets in {time_str}"

    def _build_menu_items(
        self,
        project_items: list[rumps.MenuItem] | None = None,
        rate_limits_map: dict[str, RateLimitInfo] | None = None,
    ) -> list:
        items: list = []

        # Rate limits per-model (solo si hay datos)
        if rate_limits_map:
            for _model, info in sorted(rate_limits_map.items()):
                item = rumps.MenuItem(
                    self._format_rate_limit(info), callback=None
                )
                items.append(item)
            items.append(rumps.separator)

        items.append(self._today_item)
        items.append(self._separator1)

        if project_items:
            items.extend(project_items)

        items.append(self._separator2)
        items.append(self._week_item)
        items.append(self._separator3)
        items.append(self._pricing_item)
        items.append(self._api_status_item)
        items.append(self._update_prices_item)
        items.append(self._refresh_item)
        items.append(self._configure_api_item)
        items.append(self._reset_item)
        items.append(self._prefs_item)
        items.append(self._separator4)
        items.append(self._quit_item)
        return items

    def _update_menu(
        self,
        report: DailyReport,
        weekly: list[DailyReport],
        display_cost: float,
        rate_limits_map: dict[str, RateLimitInfo] | None = None,
        api_source: bool = False,
    ) -> None:
        # Today summary (muestra display_cost con offset aplicado)
        source_tag = " (API)" if api_source else ""
        self._today_item.title = (
            f"Today: ${display_cost:.2f}{source_tag}  "
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
        self.menu = self._build_menu_items(project_items, rate_limits_map)


def main() -> None:
    ClaudeMonitorApp().run()


if __name__ == "__main__":
    main()
