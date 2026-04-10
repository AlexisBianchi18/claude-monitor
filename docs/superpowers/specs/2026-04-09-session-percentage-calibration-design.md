# Feature 1: Calibrar porcentaje de sesion

## Problema

Los `PLAN_LIMITS` actuales (tokens por modelo por sesion) estan sobreestimados
~100-500x respecto a los limites reales de Anthropic. Esto causa que la app
muestre 0.2% cuando claude.ai muestra 31%.

Anthropic no publica limites fijos de tokens — son dinamicos y opacos. Los
limites reales se basan en **costo**, no en tokens crudos, porque Opus consume
~5x mas presupuesto que Sonnet por token.

## Solucion: presupuesto de sesion basado en costo

Reemplazar el calculo `sum(tokens) / sum(token_limits)` por
`equivalent_api_cost / session_budget_usd`.

La app ya calcula `equivalent_api_cost` usando `PRICING_TABLE`. Solo falta
definir el denominador: un presupuesto de sesion en USD-equivalentes por plan.

### Dato de calibracion

Medicion simultanea (2026-04-09):

| Metrica          | App    | Claude.ai |
|------------------|--------|-----------|
| Overall sesion   | 0.2%   | 31%       |
| Costo equivalente| $3.56  | —         |
| Reset            | 3h 23m | 2h 22m    |

`session_budget_usd = $3.56 / 0.31 = $11.48` para Max 5x.

## Cambios por componente

### config.py

Nuevo dict con presupuestos por plan:

```python
SESSION_BUDGETS: dict[str, float] = {
    "pro":     2.30,     # 11.48 / 5
    "max_5x":  11.48,    # calibrado 2026-04-09
    "max_20x": 45.92,    # 11.48 * 4
}
```

Nuevas properties en `ConfigManager`:

- `session_budget_usd` — retorna custom override o default por plan
- `set_session_budget(value)` — persiste en config.json

`PLAN_LIMITS` se mantiene temporalmente pero deja de usarse para calculo de
porcentaje.

### models.py

`ModelUsageStatus` cambia de tokens a costo:

```python
@dataclass
class ModelUsageStatus:
    model: str
    cost_usd: float
    session_budget_usd: float

    @property
    def percentage(self) -> float:
        if self.session_budget_usd <= 0:
            return 0.0
        return (self.cost_usd / self.session_budget_usd) * 100.0
```

Se eliminan `tokens_used`, `tokens_limit`, `tokens_remaining`.

`PlanReport` agrega `session_budget_usd`:

```python
@dataclass
class PlanReport:
    plan_name: str
    models: list[ModelUsageStatus]
    estimated_reset: datetime | None
    equivalent_api_cost: float
    session_budget_usd: float

    @property
    def overall_percentage(self) -> float:
        if self.session_budget_usd <= 0:
            return 0.0
        return (self.equivalent_api_cost / self.session_budget_usd) * 100.0
```

### log_parser.py

`get_plan_report()` cambia firma:

```python
def get_plan_report(
    self,
    plan_name: str,
    session_budget_usd: float,       # antes: daily_limits dict
    reset_anchor_utc: datetime | None = None,
    reset_window_hours: int = 5,
    target_date: date | None = None,
    *,
    _now: datetime | None = None,
) -> PlanReport:
```

Internamente usa `cost_by_model` del window/daily report para crear
`ModelUsageStatus` por costo en vez de por tokens.

### app.py

- Adapta llamada a `get_plan_report()`: pasa `session_budget_usd` en vez de
  `daily_token_limits`
- Menu per-modelo muestra contribucion de costo al presupuesto
- Modo `text` muestra `$3.00 / $11.48` en vez de `1.5M / 10M`
- Nuevo item "Calibrate..." en submenu Preferences

### cli.py

Nuevos flags:

```
--calibrate PCT     Recalibra session_budget con el % de claude.ai
--reset-in MIN      Recalibra anchor con minutos hasta reset de claude.ai
```

### extra_usage.py

`calculate_extra_usage()` actualmente compara `tokens_used` vs `tokens_limit`
para determinar si el plan esta agotado y calcular tokens extra. Con el nuevo
modelo, cambia a comparar `equivalent_api_cost` vs `session_budget_usd`:

- Plan agotado: `equivalent_api_cost >= session_budget_usd`
- Costo extra: `equivalent_api_cost - session_budget_usd`

La funcion recibe `PlanReport` que ya contiene ambos valores.

### tests/

Actualizar todos los tests que construyen `ModelUsageStatus` y `PlanReport` con
los nuevos campos. Actualizar tests de `get_plan_report()` para la nueva firma.

## Calibracion del reset time

El anchor esta desfasado ~1h. Se corrige junto con la calibracion:

```python
# Usuario ingresa minutos hasta reset (de claude.ai)
next_reset = now + timedelta(minutes=user_minutes)
# Calcula anchor que produce ese reset
new_anchor = next_reset - timedelta(hours=window_hours)
```

## Que NO cambia

- Parsing de logs JSONL
- Deduplicacion por message.id
- Calculo de `equivalent_api_cost` / `cost_by_model` en el parser
- Estructura general del menu (items, separadores, submenus)
- Alertas de threshold (siguen usando `overall_percentage`)
- Auto-update
- Modo API
