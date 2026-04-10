"""Claude Code Cost Monitor — macOS Menu Bar App."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date

import rumps

try:
    from AppKit import NSFont, NSFontAttributeName
    from Foundation import NSAttributedString

    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False

from .api_client import get_cost_report, get_last_error, get_rate_limits, invalidate_key
from .config import PLAN_LIMITS, ConfigManager
from .extra_usage import calculate_extra_usage
from .log_parser import ClaudeLogParser
from .models import DailyReport, ExtraUsageStatus, PlanReport, RateLimitInfo
from .pricing_fetcher import get_pricing_age, should_fetch, update_pricing
from .updater import check_for_update, detect_app_path, download_and_replace, restart_app

logger = logging.getLogger(__name__)

PLAN_DISPLAY_NAMES: dict[str, str] = {
    "pro": "Pro",
    "max_5x": "Max 5x",
    "max_20x": "Max 20x",
}

MODEL_SHORT_NAMES: dict[str, str] = {
    "claude-opus-4-6": "opus",
    "claude-sonnet-4-6": "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
}


def _short_model_name(model: str) -> str:
    """Nombre corto del modelo para el titulo: claude-opus-4-6 -> opus."""
    return MODEL_SHORT_NAMES.get(model, model.replace("claude-", "").split("-")[0])


def _noop(_sender: rumps.MenuItem) -> None:
    """No-op callback para mantener items habilitados (no grayed-out)."""


def _apply_mono_style(item: rumps.MenuItem, size: float = 12.0) -> None:
    """Aplica fuente monoespaciada al item para alineacion correcta."""
    if not _HAS_APPKIT:
        return
    try:
        font = NSFont.fontWithName_size_("Menlo", size)
        if font is None:
            return
        attrs = {NSFontAttributeName: font}
        attr_str = NSAttributedString.alloc().initWithString_attributes_(
            item.title, attrs
        )
        item._menuitem.setAttributedTitle_(attr_str)
    except Exception:
        pass


def _render_bar(percentage: float, width: int = 12) -> str:
    """Renderiza una barra de progreso con caracteres Unicode."""
    clamped = max(0.0, min(percentage, 100.0))
    filled = round(clamped / 100.0 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _format_tokens_short(tokens: int) -> str:
    """Formatea tokens en formato corto: 2.1M, 500K, 42."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)


def _format_reset_time(seconds: int) -> str:
    """Formatea segundos restantes en formato legible."""
    if seconds <= 0:
        return "now"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class ClaudeMonitorApp(rumps.App):
    """App de barra de menu que muestra el costo de Claude Code."""

    def __init__(self) -> None:
        super().__init__("C \u2026", quit_button=None)
        self.parser = ClaudeLogParser()
        self.config = ConfigManager()

        # Items fijos del menu
        self._today_item = rumps.MenuItem("Today: loading...", callback=_noop)
        self._separator1 = rumps.separator
        # Project items se generan dinamicamente
        self._separator2 = rumps.separator
        self._week_item = rumps.MenuItem("This week: ...", callback=_noop)
        self._separator3 = rumps.separator
        self._pricing_item = rumps.MenuItem("Prices: built-in defaults", callback=_noop)
        self._api_status_item = rumps.MenuItem("API: not configured", callback=_noop)
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
        self._style_item = rumps.MenuItem(
            "Style: Bars \u2588\u2588\u2588", callback=self._on_toggle_style
        )
        self._extra_usage_item = rumps.MenuItem(
            "Extra Usage Limit\u2026", callback=self._on_configure_extra_usage
        )
        self._prefs_item = rumps.MenuItem(
            "Preferences\u2026", callback=self._on_open_prefs
        )
        self._separator4 = rumps.separator
        self._quit_item = rumps.MenuItem("Quit", callback=self._on_quit)

        self._last_models_used: list[str] = []
        self._update_available: bool = False
        self._update_version: str | None = None
        self._update_url: str | None = None

        self.menu = self._build_menu_items()

        # Timer de auto-refresh
        self._timer = rumps.Timer(self._on_timer, self.config.refresh_interval)
        self._timer.start()

        # Refresh inmediato al arrancar
        self._refresh()

        # Intentar actualizar precios en background al iniciar
        self._maybe_fetch_pricing()

        # Chequear actualizaciones al iniciar
        self._maybe_check_for_update()

    # --- Callbacks ---

    def _on_timer(self, sender: rumps.Timer) -> None:
        self._refresh()
        self._maybe_fetch_pricing()
        self._maybe_poll_api()
        self._maybe_check_for_update()

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

    def _on_select_plan(self, plan_key: str) -> None:
        """Cambia el plan de suscripción y refresca."""
        self.config.set_plan(plan_key)
        self._refresh()

    def _on_toggle_style(self, sender: rumps.MenuItem) -> None:
        """Alterna entre estilo bar y text."""
        self.config.toggle_display_style()
        self._refresh()

    def _on_select_model(self, model: str | None) -> None:
        """Selecciona o deselecciona un modelo para filtrar el titulo."""
        current = self.config.selected_model
        if model is not None and model == current:
            self.config.set_selected_model(None)
        else:
            self.config.set_selected_model(model)
        self._refresh()

    def _on_configure_extra_usage(self, sender: rumps.MenuItem) -> None:
        """Muestra un dialogo para configurar el limite de extra usage."""
        current = self.config.extra_usage_limit_usd
        response = rumps.Window(
            title="Extra Usage Limit",
            message="Monthly extra usage limit in USD (0 = disabled).",
            default_text=str(current),
            ok="Save",
            cancel="Cancel",
            dimensions=(200, 24),
        ).run()
        if response.clicked == 1:
            try:
                val = float(response.text.strip())
                self.config.set_extra_usage_limit(val)
                self._refresh()
            except ValueError:
                pass

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

    # --- Auto-update ---

    def _maybe_check_for_update(self) -> None:
        """Chequea actualizaciones en background si pasaron 24h."""
        if not self.config.auto_update_enabled:
            return
        if not self.config.should_check_for_update():
            return
        thread = threading.Thread(
            target=self._check_update_background, daemon=True
        )
        thread.start()

    def _check_update_background(self) -> None:
        """Ejecuta check en un thread. Notifica si hay update."""
        version, url = check_for_update()
        self.config.mark_update_checked()
        if version and url:
            self._update_available = True
            self._update_version = version
            self._update_url = url
            rumps.notification(
                title="Claude Monitor Update",
                subtitle=f"Version {version} available",
                message="Click 'Update' in the menu to install.",
            )

    def _on_update(self, sender: rumps.MenuItem) -> None:
        """Callback cuando el usuario hace click en el item de update."""
        app_path = detect_app_path()

        if app_path is None:
            rumps.alert(
                title="Update Available",
                message=(
                    f"Version {self._update_version} is available.\n"
                    "You're running from source — auto-update is not available.\n"
                    "Pull the latest code from GitHub to update."
                ),
            )
            return

        response = rumps.alert(
            title=f"Update to v{self._update_version}?",
            message="The app will download the update, replace itself, and restart.",
            ok="Update Now",
            cancel="Later",
        )
        if response != 1:
            return

        sender.title = "Updating..."
        thread = threading.Thread(
            target=self._download_update_background,
            args=(self._update_url, app_path),
            daemon=True,
        )
        thread.start()

    def _download_update_background(self, url: str, app_path: str) -> None:
        """Descarga e instala la actualización en background."""
        error = download_and_replace(url, app_path)
        if error:
            rumps.notification(
                title="Update Failed",
                subtitle="",
                message=error,
            )
            return
        restart_app(app_path)

    # --- Logica de refresh ---

    def _refresh(self) -> None:
        try:
            today = date.today()
            report = self.parser.get_daily_report(today)
            weekly = self.parser.get_weekly_report()

            self._last_models_used = sorted(report.models_used)

            if self.config.usage_mode == "subscription":
                self._refresh_subscription(today, report, weekly)
            else:
                self._refresh_api(today, report, weekly)
        except Exception:
            self.title = "C err"

    def _refresh_api(
        self, today: date, report: DailyReport, weekly: list[DailyReport]
    ) -> None:
        """Refresh en modo API (comportamiento original)."""
        offset = self.config.get_daily_offset(today)
        display_cost = max(0.0, report.total_cost - offset)

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

        selected = self.config.selected_model
        model_suffix = ""
        if selected and selected in report.cost_by_model:
            shown_cost = report.cost_by_model[selected]
            model_suffix = f" {_short_model_name(selected)}"
        else:
            shown_cost = display_cost

        self._update_title(
            shown_cost, display_cost, today,
            api_source=api_cost is not None, model_suffix=model_suffix,
        )
        self._update_menu(
            report, weekly, display_cost, rate_limits_map, api_cost is not None
        )

        age = get_pricing_age()
        self._pricing_item.title = (
            f"Prices: {age}" if age else "Prices: built-in defaults"
        )
        self._update_api_status()

    def _refresh_subscription(
        self, today: date, report: DailyReport, weekly: list[DailyReport]
    ) -> None:
        """Refresh en modo suscripcion."""
        plan_report = self.parser.get_plan_report(
            plan_name=self.config.plan,
            session_budget_usd=self.config.session_budget_usd,
            reset_anchor_utc=self.config.reset_anchor_utc,
            reset_window_hours=self.config.reset_window_hours,
            target_date=today,
        )

        extra = calculate_extra_usage(
            plan_report,
            self.config.extra_usage_limit_usd,
            self.config.extra_usage_alert_pct,
        )

        selected = self.config.selected_model
        if selected:
            model_status = next(
                (m for m in plan_report.models if m.model == selected), None
            )
            pct = model_status.percentage if model_status else 0.0
            model_suffix = f" {_short_model_name(selected)}"
        else:
            pct = plan_report.overall_percentage
            model_suffix = ""

        if extra is None:
            if pct >= 95:
                self.title = f"\U0001f534 {pct:.1f}%{model_suffix}"
            elif pct >= 80:
                self.title = f"\u26a0 {pct:.1f}%{model_suffix}"
            else:
                self.title = f"C {pct:.1f}%{model_suffix}"
        else:
            if extra.is_exhausted:
                self.title = f"\U0001f534 ${extra.cost_usd:.2f}/${extra.limit_usd:.0f}"
            elif extra.is_over_alert:
                self.title = f"\u26a0 ${extra.cost_usd:.2f}/${extra.limit_usd:.0f}"
            else:
                self.title = f"C ${extra.cost_usd:.2f}/${extra.limit_usd:.0f}"

            # Alerta de extra usage
            if extra.is_over_alert and not self.config.has_extra_alert_fired_today(today):
                self.config.mark_extra_alert_fired(today)
                rumps.notification(
                    title="Extra Usage Alert",
                    subtitle="Approaching extra usage limit",
                    message=(
                        f"${extra.cost_usd:.2f} of ${extra.limit_usd:.2f} used "
                        f"({extra.percentage:.0f}%)"
                    ),
                )

        self._update_subscription_menu(plan_report, report, weekly, extra)

    def _update_subscription_menu(
        self,
        plan_report: PlanReport,
        report: DailyReport,
        weekly: list[DailyReport],
        extra: ExtraUsageStatus | None = None,
    ) -> None:
        """Construye el menu para modo suscripcion."""
        style = self.config.display_style
        reset_str = _format_reset_time(plan_report.seconds_until_reset)

        items: list = []

        # Today summary (effective tokens = sin cache_read, coherente con %)
        effective_total = sum(report.effective_tokens_by_model.values())
        total_tokens_str = _format_tokens_short(effective_total)
        equiv_str = f"${plan_report.equivalent_api_cost:.2f}"
        today_item = rumps.MenuItem(
            f"Today: {total_tokens_str} tokens (\u2248 {equiv_str} API)",
            callback=_noop,
        )
        items.append(today_item)
        items.append(rumps.separator)

        # Model filter: "All" item + per-model items with selection
        selected = self.config.selected_model
        all_prefix = "\u2713" if not selected else "  "
        all_item = rumps.MenuItem(
            f"{all_prefix} All models",
            callback=lambda sender: self._on_select_model(None),
        )
        _apply_mono_style(all_item)
        items.append(all_item)

        for m in plan_report.models:
            short_name = m.model.replace("claude-", "").replace("-20251001", "")
            prefix = "\u2713" if selected == m.model else "  "
            if style == "bar":
                bar = _render_bar(m.percentage)
                line = f"{prefix} {short_name:<14}{bar} {m.percentage:>5.1f}%"
            else:
                budget_str = f"${m.session_budget_usd:.2f}"
                line = f"{prefix} {short_name:<14}${m.cost_usd:.2f} / {budget_str}"
            model_item = rumps.MenuItem(
                line,
                callback=lambda sender, model=m.model: self._on_select_model(model),
            )
            _apply_mono_style(model_item)
            items.append(model_item)

        items.append(rumps.separator)

        # Extra usage line (only when active)
        if extra is not None:
            extra_line = (
                f"  Extra: ${extra.cost_usd:.2f} / ${extra.limit_usd:.2f}"
                f"  ({extra.percentage:.1f}%)"
            )
            extra_item = rumps.MenuItem(extra_line, callback=_noop)
            _apply_mono_style(extra_item)
            items.append(extra_item)
            items.append(rumps.separator)

        # Reset timer
        items.append(rumps.MenuItem(
            f"Reset: \u21bb {reset_str}", callback=_noop
        ))
        items.append(rumps.separator)

        # Projects
        max_projects = self.config.max_projects
        for p in report.projects[:max_projects]:
            tok_str = _format_tokens_short(p.total_tokens)
            proj_item = rumps.MenuItem(
                f"  {p.display_name:<28} {tok_str}",
                callback=_noop,
            )
            _apply_mono_style(proj_item)
            items.append(proj_item)

        items.append(rumps.separator)

        # Weekly summary
        week_tokens = sum(r.total_tokens for r in weekly)
        week_cost = sum(r.total_cost for r in weekly)
        items.append(rumps.MenuItem(
            f"Week: {_format_tokens_short(week_tokens)} tokens "
            f"(\u2248 ${week_cost:.2f} API)",
            callback=_noop,
        ))
        items.append(rumps.separator)

        # Plan submenu
        current_plan = self.config.plan
        plan_display = PLAN_DISPLAY_NAMES.get(current_plan, current_plan)
        plan_menu = rumps.MenuItem(f"Plan: {plan_display}")
        for key in PLAN_LIMITS:
            label = PLAN_DISPLAY_NAMES.get(key, key)
            if key == current_plan:
                label = f"\u2713 {label}"
            plan_menu[label] = rumps.MenuItem(
                label, callback=lambda sender, k=key: self._on_select_plan(k)
            )
        items.append(plan_menu)

        style_label = "Bars \u2588\u2588\u2588" if style == "bar" else "Text 0/0"
        self._style_item.title = f"Style: {style_label}"
        items.append(self._style_item)
        items.append(self._extra_usage_item)
        items.append(self._refresh_item)
        items.append(self._reset_item)
        items.append(self._prefs_item)
        if self._update_available and self._update_version:
            items.append(rumps.separator)
            items.append(rumps.MenuItem(
                f"Update available (v{self._update_version})",
                callback=self._on_update,
            ))
        items.append(rumps.separator)
        items.append(self._quit_item)

        self.menu.clear()
        self.menu = items

    def _update_title(
        self,
        shown_cost: float,
        alert_cost: float,
        today: date,
        *,
        api_source: bool = False,
        model_suffix: str = "",
    ) -> None:
        threshold = self.config.alert_threshold
        suffix = " \u2713" if api_source else ""
        if alert_cost >= threshold:
            self.title = f"\u26a0 ${shown_cost:.2f}{suffix}{model_suffix}"
            # Enviar notificacion una vez por dia (basada en costo total, no filtrado)
            if not self.config.has_alert_fired_today(today):
                self.config.mark_alert_fired(today)
                rumps.notification(
                    title="Claude Code Cost Alert",
                    subtitle=f"Daily cost exceeded ${threshold:.2f}",
                    message=f"Current cost: ${alert_cost:.2f}",
                )
        else:
            self.title = f"C ${shown_cost:.2f}{suffix}{model_suffix}"

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
        return f"{short_name}: {pct:.1f}% used \u00b7 resets in {time_str}"

    def _build_menu_items(
        self,
        project_items: list[rumps.MenuItem] | None = None,
        rate_limits_map: dict[str, RateLimitInfo] | None = None,
        model_items: list[rumps.MenuItem] | None = None,
    ) -> list:
        items: list = []

        # Rate limits per-model (solo si hay datos)
        if rate_limits_map:
            for _model, info in sorted(rate_limits_map.items()):
                item = rumps.MenuItem(
                    self._format_rate_limit(info), callback=_noop
                )
                _apply_mono_style(item)
                items.append(item)
            items.append(rumps.separator)

        items.append(self._today_item)
        items.append(self._separator1)

        if project_items:
            items.extend(project_items)

        if model_items:
            items.append(rumps.separator)
            items.extend(model_items)

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
        if self._update_available and self._update_version:
            items.append(rumps.separator)
            items.append(rumps.MenuItem(
                f"Update available (v{self._update_version})",
                callback=self._on_update,
            ))
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
                callback=_noop,
            )
            _apply_mono_style(item)
            project_items.append(item)

        # Model items for filter
        selected = self.config.selected_model
        model_items: list[rumps.MenuItem] = []
        if report.models_used:
            all_prefix = "\u2713" if not selected else "  "
            all_item = rumps.MenuItem(
                f"{all_prefix} All models",
                callback=lambda sender: self._on_select_model(None),
            )
            _apply_mono_style(all_item)
            model_items.append(all_item)
            for model in sorted(report.models_used):
                short = model.replace("claude-", "").replace("-20251001", "")
                cost = report.cost_by_model.get(model, 0.0)
                prefix = "\u2713" if selected == model else "  "
                item = rumps.MenuItem(
                    f"{prefix} {short:<14} ${cost:.2f}",
                    callback=lambda sender, m=model: self._on_select_model(m),
                )
                _apply_mono_style(item)
                model_items.append(item)

        # Weekly summary
        week_total = sum(r.total_cost for r in weekly)
        avg = week_total / len(weekly) if weekly else 0.0
        self._week_item.title = (
            f"This week: ${week_total:.2f}  (avg ${avg:.2f}/day)"
        )

        # Reconstruir menu
        self.menu.clear()
        self.menu = self._build_menu_items(project_items, rate_limits_map, model_items)


def main() -> None:
    ClaudeMonitorApp().run()


if __name__ == "__main__":
    main()
