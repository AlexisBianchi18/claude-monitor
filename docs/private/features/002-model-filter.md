---
id: "002"
title: Filtro por modelo en barra de menu
status: done
priority: medium
complexity: low
created: 2026-04-09
updated: 2026-04-09
tags: [ui, subscription, api]
plan: docs/private/plans/2026-04-09-model-filter.md
---

## Descripcion

Permitir al usuario hacer click sobre un modelo en el menu desplegable para
filtrar la barra de titulo y mostrar solo el uso/costo de ese modelo individual.
Actualmente la barra siempre muestra datos agregados de todos los modelos.

## Motivacion

Cuando se usan multiples modelos (opus, sonnet, haiku), el porcentaje o costo
agregado no da visibilidad sobre cuanto se ha consumido de un modelo especifico.
El usuario quiere poder ver rapidamente "cuanto opus me queda" sin tener que
abrir el menu completo cada vez.

## Analisis

### Estado actual

- `DailyReport` tiene `tokens_by_model` y `effective_tokens_by_model` pero NO
  `cost_by_model`
- Los items de modelo en el menu usan callback `_noop` (display-only)
- En subscription mode: `PlanReport.models` es `list[ModelUsageStatus]` con
  porcentaje individual por modelo
- En API mode: solo hay `total_cost` agregado, sin desglose por modelo
- `ConfigManager` no tiene concepto de modelo seleccionado

### Cambios necesarios

**models.py** — Agregar `cost_by_model: dict[str, float]` a `DailyReport`.

**log_parser.py** — Acumular `cost_by_model` en `_parse_project()` y
`get_daily_report()`, siguiendo el patron existente de `tokens_by_model`.

**config.py** — Agregar propiedad `selected_model: str | None` a
`ConfigManager`. Persiste en `config.json`. `None` = todos los modelos.

**app.py** — Logica de filtrado en refresh y callbacks en items de modelo:

1. Items de modelo pasan de `_noop` a `_on_select_model(model)` callback
2. Se agrega item "All" al inicio de la lista de modelos
3. El modelo activo se marca con `✓`
4. Click en modelo activo = toggle a "All" (deselecciona)
5. Titulo filtrado: `"C 45.2% opus"` (subscription) o `"C $0.18 opus"` (API)
6. Alertas de threshold siguen evaluandose contra el total, no el filtrado

### Formato del titulo

| Modo | Sin filtro (actual) | Con filtro |
|------|-------------------|------------|
| Subscription | `C 45.2%` | `C 45.2% opus` |
| Subscription (alert) | `⚠ 85.0%` | `⚠ 85.0% opus` |
| API | `C $0.42` | `C $0.18 opus` |
| API (alert) | `⚠ $5.20` | `⚠ $2.10 opus` |
| Extra usage | `C $2.00/$10` | Sin cambio (extra no filtra por modelo) |

Nombre corto del modelo: `claude-opus-4-6` → `opus`, `claude-sonnet-4-6` →
`sonnet`, `claude-haiku-4-5-20251001` → `haiku`.

### Interaccion

- Click en modelo → selecciona, titulo cambia, item se marca con ✓
- Click en modelo ya seleccionado → deselecciona (vuelve a "All")
- Click en "All" → deselecciona modelo (vuelve al comportamiento actual)
- "All" se marca con ✓ cuando no hay filtro activo
- La seleccion persiste en `config.json` entre reinicios

### Flujo de datos

```
User click en "opus-4-6"
    → _on_select_model("claude-opus-4-6")
    → config.set_selected_model("claude-opus-4-6")
    → _refresh()
    → _refresh_subscription() o _refresh_api()
        → si selected_model: usar datos individuales del modelo
        → titulo: "C {pct}% opus" o "C ${cost} opus"
    → _update_subscription_menu() o _update_menu()
        → items de modelo con ✓ en el seleccionado
        → item "All" con ✓ si no hay filtro
```

## Decisiones

- **Persistencia**: si, en config.json (campo `selected_model`)
- **Alcance**: ambos modos (subscription y API)
- **Formato titulo**: formato actual + nombre corto del modelo como sufijo
- **Toggle**: click en modelo activo deselecciona + item "All" siempre visible
- **Alertas**: siguen evaluandose contra totales (el filtro es solo visual)
- **Extra usage**: no se filtra por modelo (aplica al total)
- **Enfoque**: estado en config + logica en app.py (no tocar parser conceptualmente,
  solo agregar `cost_by_model` al DailyReport para tener el dato disponible)

## Tareas

- [x] Agregar `cost_by_model` a `DailyReport` en models.py
- [x] Acumular `cost_by_model` en log_parser.py (_parse_project + get_daily_report)
- [x] Agregar `selected_model` property a ConfigManager en config.py
- [x] Implementar callbacks de seleccion de modelo en app.py
- [x] Agregar item "All" y marca ✓ en menu de modelos
- [x] Filtrar titulo en _refresh_subscription() segun modelo seleccionado
- [x] Filtrar titulo en _refresh_api() segun modelo seleccionado
- [x] Tests para cost_by_model en test_models.py y test_parser.py
- [x] Tests para selected_model en test_config.py
- [x] Tests para logica de filtrado en app (si aplica)
- [x] Actualizar CLAUDE.md con nuevo campo y conteo de tests
