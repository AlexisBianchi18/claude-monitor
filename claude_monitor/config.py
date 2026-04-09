"""Configuración y tabla de precios para Claude Code Cost Monitor."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

CLAUDE_LOGS_DIR = Path.home() / ".claude" / "projects"

# --- Precios por modelo (USD por millón de tokens) ---


@dataclass(frozen=True)
class ModelPricing:
    """Precios de un modelo en USD por millón de tokens."""

    input: float
    output: float
    cache_read: float
    cache_create_5m: float
    cache_create_1h: float


# Precios oficiales de https://platform.claude.com/docs/en/about-claude/pricing
# Última verificación: 2026-04-08
PRICING_TABLE: dict[str, ModelPricing] = {
    # Opus 4.6: $5/$25 base, cache read 0.1x, 5m write 1.25x, 1h write 2x
    "claude-opus-4-6": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    # Sonnet 4.6: $3/$15 base
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0, 0.30, 3.75, 6.0),
    # Haiku 4.5: $1/$5 base
    "claude-haiku-4-5-20251001": ModelPricing(1.0, 5.0, 0.10, 1.25, 2.0),
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
CONFIG_FILE = CONFIG_DIR / "config.json"

# --- Plan de suscripcion ---
VALID_USAGE_MODES = {"api", "subscription"}
VALID_DISPLAY_STYLES = {"bar", "text"}
DEFAULT_RESET_HOUR_UTC = 7  # ~midnight Chile

# Limites diarios estimados de tokens por plan (ajustables por el usuario)
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "pro": {
        "claude-opus-4-6": 2_000_000,
        "claude-sonnet-4-6": 10_000_000,
        "claude-haiku-4-5-20251001": 30_000_000,
    },
    "max_5x": {
        "claude-opus-4-6": 10_000_000,
        "claude-sonnet-4-6": 50_000_000,
        "claude-haiku-4-5-20251001": 150_000_000,
    },
    "max_20x": {
        "claude-opus-4-6": 40_000_000,
        "claude-sonnet-4-6": 200_000_000,
        "claude-haiku-4-5-20251001": 600_000_000,
    },
}


class ConfigManager:
    """Gestiona configuración persistente en ~/.claude-monitor/config.json."""

    _defaults: dict = {
        "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        "cost_alert_threshold_usd": COST_ALERT_THRESHOLD_USD,
        "max_projects_in_menu": MAX_PROJECTS_IN_MENU,
        "anthropic_api_key": "",
        "usage_mode": "api",
        "plan": "max_5x",
        "display_style": "bar",
        "reset_hour_utc": DEFAULT_RESET_HOUR_UTC,
        "auto_update_enabled": True,
        "last_update_check": "",
        "extra_usage_limit_usd": 0.0,
        "extra_usage_alert_pct": 90.0,
    }

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or CONFIG_FILE
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        """Carga la configuración desde disco. Si falla, usa defaults."""
        if self.config_path.is_file():
            try:
                raw = self.config_path.read_text(encoding="utf-8")
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    # Merge con defaults para agregar keys nuevas
                    self._data = {**self._defaults, **loaded}
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._data = dict(self._defaults)

    def save(self) -> None:
        """Guarda la configuración a disco con permisos restrictivos (0600)."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._data, indent=2) + "\n", encoding="utf-8"
        )
        # Restringir permisos ya que puede contener API key
        self.config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    # --- Daily offset (para reset de contador) ---

    def get_daily_offset(self, target_date: date) -> float:
        """Retorna el offset de costo para una fecha dada."""
        offsets = self._data.get("daily_offsets", {})
        return float(offsets.get(target_date.isoformat(), 0.0))

    def set_daily_offset(self, target_date: date, offset: float) -> None:
        """Guarda un offset de costo para una fecha y persiste."""
        offsets = self._data.setdefault("daily_offsets", {})
        offsets[target_date.isoformat()] = offset
        self.save()

    # --- Alert tracking ---

    def has_alert_fired_today(self, target_date: date) -> bool:
        """Verifica si la alerta de costo ya se disparó hoy."""
        return self._data.get("last_alert_date") == target_date.isoformat()

    def mark_alert_fired(self, target_date: date) -> None:
        """Marca que la alerta se disparó hoy y persiste."""
        self._data["last_alert_date"] = target_date.isoformat()
        self.save()

    # --- Acceso a propiedades de config ---

    @property
    def refresh_interval(self) -> int:
        return int(self._data.get("refresh_interval_seconds", REFRESH_INTERVAL_SECONDS))

    @property
    def alert_threshold(self) -> float:
        return float(self._data.get("cost_alert_threshold_usd", COST_ALERT_THRESHOLD_USD))

    @property
    def max_projects(self) -> int:
        return int(self._data.get("max_projects_in_menu", MAX_PROJECTS_IN_MENU))

    # --- API key ---

    @property
    def api_key(self) -> str:
        """Retorna la API key configurada, o cadena vacía si no hay."""
        return str(self._data.get("anthropic_api_key", ""))

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def api_key_type(self) -> str:
        """Retorna 'admin', 'standard', o '' según el prefijo de la key."""
        key = self.api_key
        if not key:
            return ""
        if key.startswith("sk-ant-admin"):
            return "admin"
        if key.startswith("sk-ant-api"):
            return "standard"
        return "unknown"

    def set_api_key(self, key: str) -> None:
        """Guarda la API key y persiste a disco."""
        self._data["anthropic_api_key"] = key
        self.save()

    # --- Plan de suscripcion ---

    @property
    def usage_mode(self) -> str:
        """'api' o 'subscription'."""
        val = str(self._data.get("usage_mode", "api"))
        return val if val in VALID_USAGE_MODES else "api"

    @property
    def plan(self) -> str:
        return str(self._data.get("plan", "max_5x"))

    @property
    def display_style(self) -> str:
        """'bar' o 'text'."""
        val = str(self._data.get("display_style", "bar"))
        return val if val in VALID_DISPLAY_STYLES else "bar"

    @property
    def reset_hour_utc(self) -> int:
        val = int(self._data.get("reset_hour_utc", DEFAULT_RESET_HOUR_UTC))
        return max(0, min(23, val))

    @property
    def daily_token_limits(self) -> dict[str, int]:
        """Limites diarios por modelo. Custom overrides se mezclan con plan defaults."""
        base = dict(PLAN_LIMITS.get(self.plan, {}))
        custom = self._data.get("daily_token_limits")
        if isinstance(custom, dict) and custom:
            base.update({k: int(v) for k, v in custom.items()})
        return base

    def set_plan(self, plan: str) -> None:
        """Cambia el plan y persiste. Limpia custom limits."""
        self._data["plan"] = plan
        self._data.pop("daily_token_limits", None)
        self.save()

    def toggle_display_style(self) -> None:
        """Alterna entre 'bar' y 'text' y persiste."""
        current = self.display_style
        self._data["display_style"] = "text" if current == "bar" else "bar"
        self.save()

    # --- Extra usage ---

    @property
    def extra_usage_limit_usd(self) -> float:
        """Limite de extra usage en USD. 0 = deshabilitado."""
        return float(self._data.get("extra_usage_limit_usd", 0.0))

    @property
    def extra_usage_alert_pct(self) -> float:
        """Umbral de alerta para extra usage (0-100)."""
        return float(self._data.get("extra_usage_alert_pct", 90.0))

    def set_extra_usage_limit(self, limit: float) -> None:
        """Guarda el limite de extra usage y persiste."""
        self._data["extra_usage_limit_usd"] = max(0.0, limit)
        self.save()

    def set_extra_usage_alert_pct(self, pct: float) -> None:
        """Guarda el umbral de alerta de extra usage y persiste."""
        self._data["extra_usage_alert_pct"] = max(0.0, min(100.0, pct))
        self.save()

    def has_extra_alert_fired_today(self, target_date: date) -> bool:
        """Verifica si la alerta de extra usage ya se disparo hoy."""
        return self._data.get("last_extra_alert_date") == target_date.isoformat()

    def mark_extra_alert_fired(self, target_date: date) -> None:
        """Marca que la alerta de extra usage se disparo hoy y persiste."""
        self._data["last_extra_alert_date"] = target_date.isoformat()
        self.save()

    # --- Auto-update ---

    @property
    def auto_update_enabled(self) -> bool:
        return bool(self._data.get("auto_update_enabled", True))

    @property
    def last_update_check(self) -> str:
        return str(self._data.get("last_update_check", ""))

    def should_check_for_update(self) -> bool:
        """True si no se ha chequeado en las últimas 24 horas."""
        raw = self.last_update_check
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
            age = datetime.now(timezone.utc) - last
            return age.total_seconds() > 24 * 3600
        except ValueError:
            return True

    def mark_update_checked(self) -> None:
        """Registra que se acaba de chequear actualizaciones."""
        self._data["last_update_check"] = datetime.now(timezone.utc).isoformat()
        self.save()
