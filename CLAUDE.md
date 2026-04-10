# Claude Code Cost Monitor — macOS Menu Bar App

## Objetivo del proyecto

Aplicacion Python para macOS que muestra en la barra de menu superior el costo
y uso de tokens de Claude Code en tiempo real, leyendo los logs locales de
`~/.claude/` sin necesidad de ninguna API key (aunque opcionalmente soporta una).

Soporta dos modos: **API** (costo USD por token) y **Subscription** (consumo
de tokens vs limites del plan Max/Pro).

---

## Stack y dependencias

```
rumps>=0.4.0          # menu bar nativa macOS
pyinstaller>=6.0      # empaquetado como .app
pytest>=7.0           # tests
```

Requiere Python 3.11+ y macOS 12+. Usar `uv` para todo:

```bash
uv sync                           # instalar dependencias
uv run python -m claude_monitor   # ejecutar menu bar app
uv run python -m claude_monitor.cli  # reporte en terminal
uv run pytest                     # correr tests
```

---

## Estructura del proyecto

```
claude_monitor/
├── __init__.py            — package marker, __version__
├── __main__.py            — entry point (python -m claude_monitor)
├── models.py              — 9 dataclasses (TokenUsage, CostEntry, ProjectStats, DailyReport, RateLimitInfo, ApiCostReport, ModelUsageStatus, PlanReport, ExtraUsageStatus)
├── config.py              — PRICING_TABLE, PLAN_LIMITS, ConfigManager (persiste en ~/.claude-monitor/config.json)
├── log_parser.py          — ClaudeLogParser: parsea ~/.claude/projects/**/*.jsonl, deduplica, calcula costos
├── extra_usage.py         — Calculo de extra usage para modo subscription
├── app.py                 — ClaudeMonitorApp(rumps.App): menu bar, timer 30s, alertas, modos api/subscription, UI styled con NSAttributedString, filtro por modelo
├── cli.py                 — CLI formatter: tabla terminal, resumen 7 dias
├── api_client.py          — Cliente HTTP para API Anthropic (rate limits, cost report con admin key)
├── pricing_fetcher.py     — Scraper HTML de precios desde docs Anthropic, cache 24h
tests/
├── conftest.py            — fixtures pytest
├── test_models.py         — 26 tests
├── test_config.py         — 74 tests
├── test_parser.py         — 53 tests
├── test_plan_report.py    — 7 tests
├── test_extra_usage.py    — 23 tests
├── test_api_client.py     — 27 tests
├── test_pricing_fetcher.py — 25 tests
├── test_version_check.py  — 16 tests
├── fixtures/
│   ├── sample_session.jsonl
│   ├── sample_subagent.jsonl
│   ├── empty.jsonl
│   └── malformed.jsonl
docs/
├── private/               — submodulo git privado (solo owner, no visible publicamente)
│   ├── features/          — sistema de gestion de features (un .md por feature)
│   │   └── _template.md   — plantilla para nuevas features
│   ├── plans/             — planes de desarrollo
│   └── memory/            — notas de sesiones de desarrollo con IA
.github/
└── workflows/
    └── release.yml        — CI: build, sign, package, release, update Homebrew tap
setup.py                   — wrapper que invoca PyInstaller para generar .app
CLAUDE.md                  — este archivo
```

Total: **252 tests**.

---

## Arquitectura

### Flujo de datos

```
~/.claude/projects/**/*.jsonl
        │
        ▼
  log_parser.py          lee y parsea lineas JSONL, deduplica por message.id
        │
        ▼
  models.py              DailyReport (costo) o PlanReport (tokens vs limites)
        │                              ▲
        ▼                              │
  app.py (rumps)         ◄── config.py (pricing, plan limits, thresholds)
        │                ◄── pricing_fetcher.py (precios actualizados via web)
        │                ◄── api_client.py (rate limits, cost report)
        ▼
  Barra de macOS         "C $0.42" o "C 45%" visible junto a WiFi y bateria
```

### Modos de uso (`usage_mode` en config.json)

- **api** (default): muestra costo USD calculado con PRICING_TABLE. Titulo: `"C $0.42"`
- **subscription**: muestra % de consumo vs limites del plan (pro, max_5x, max_20x). Titulo: `"C 45%"`. Ventana de uso de 5h rolling (configurable via `reset_anchor_utc` y `reset_window_hours`)

### Version check

- Item fijo "Version X.Y.Z" en el menú (antes de Quit)
- Al hacer click: ejecuta `brew info --cask alexisbianchi18/tap/claude-monitor --json=v2` en background
- Si hay versión nueva: muestra alert con instrucciones (`brew upgrade claude-monitor`)
- Si está al día: muestra "You're Up to Date"
- Si Homebrew no está instalado: muestra link a GitHub Releases como fallback
- `__version__` en `__init__.py` es la fuente de verdad para comparar versiones

---

## Formato real de logs JSONL

Los campos relevantes estan anidados bajo `message`, NO en la raiz:

```json
{
  "type": "assistant",
  "timestamp": "2025-04-08T14:23:11.000Z",
  "message": {
    "id": "msg_xxx",
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 1240,
      "output_tokens": 387,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0
    }
  }
}
```

- `costUSD` NO existe en los logs reales — se calcula con la pricing table
- Streaming genera multiples lineas con el mismo `message.id` — se deduplica (last wins)
- Subagentes: `<session-uuid>/subagents/agent-*.jsonl`

---

## Patrones de UI en app.py

### Items habilitados (no grayed-out)

Los items informativos (today, week, proyectos, modelos, rate limits) usan un
callback no-op en vez de `callback=None` para que macOS los renderice como
texto negro habilitado en lugar de gris disabled:

```python
def _noop(_sender):
    pass

rumps.MenuItem("Today: ...", callback=_noop)  # negro, legible
# vs
rumps.MenuItem("Today: ...", callback=None)   # gris, poco visible
```

### Fuente monoespaciada para alineacion

Items que necesitan alineacion (barras, proyectos, rate limits) usan
`NSAttributedString` via PyObjC para aplicar fuente Menlo:

```python
def _apply_mono_style(item, size=12.0):
    font = NSFont.fontWithName_size_("Menlo", size)
    attrs = {NSFontAttributeName: font}
    attr_str = NSAttributedString.alloc().initWithString_attributes_(item.title, attrs)
    item._menuitem.setAttributedTitle_(attr_str)
```

El import de AppKit/Foundation esta en `try/except` con flag `_HAS_APPKIT` para
no romper en tests.

### Barras de progreso

Caracteres `█` (U+2588, lleno) y `░` (U+2591, vacio), ancho 12 chars:
```
████████░░░░  67%
```

---

## Archivos de config del usuario

- `~/.claude-monitor/config.json` — preferencias persistentes (usage_mode, plan, display_style, threshold, offsets, api_key, reset_anchor_utc, reset_window_hours)
- `~/.claude-monitor/pricing_cache.json` — cache de precios scrapeados

---

## Build y distribucion

Se usa **PyInstaller** (NO py2app):

```bash
uv run python setup.py   # genera bundle .app con LSUIElement=True (no aparece en Dock)
```

### Repositorios

| Repo | Proposito |
|------|-----------|
| `AlexisBianchi18/claude-monitor` | Codigo fuente principal |
| `AlexisBianchi18/homebrew-tap` | Cask formula de Homebrew (auto-actualizado) |

### Pipeline de release (GitHub Actions)

El workflow `.github/workflows/release.yml` se dispara con `git push` de un tag `v*`:

```
Tag push v1.2.0
  → Build .app con PyInstaller
  → Ad-hoc codesign (evita error "app dañada" en macOS)
  → ZIP con ditto (preserva atributos macOS, symlinks, permisos)
  → DMG con create-dmg (drag-to-Applications)
  → GitHub Release con ZIP + DMG
  → Auto-update del Homebrew tap (version + SHA256 en Casks/claude-monitor.rb)
```

El paso "Update Homebrew tap" necesita un secret `HOMEBREW_TAP_TOKEN` (Personal
Access Token de GitHub con scope `repo`) configurado en Settings > Secrets del
repo principal.

### Instalacion para usuarios

```bash
brew install --cask alexisbianchi18/tap/claude-monitor   # Homebrew (recomendado)
brew upgrade claude-monitor                               # actualizar
```

Alternativas: descargar DMG o ZIP desde GitHub Releases.

---

## Notas importantes

- **Nunca leer archivos fuera de `~/.claude/`**. El parser no debe aceptar
  rutas arbitrarias.
- **Privacidad**: la app solo lee campos numericos (`usage`, `timestamp`,
  `model`). No leer ni exponer el campo `content` de ninguna linea.
- **Thread safety**: `rumps.Timer` corre en el hilo principal. El parser es
  sincrono. Las llamadas de red (api_client, pricing_fetcher) corren en
  `threading.Thread` con `daemon=True`.
- **Deduplicacion**: streaming genera multiples lineas con el mismo
  `message.id`. El parser usa `entries_by_id[msg_id] = entry` (last wins).
- **Calculo de costo**: `costUSD` no existe en logs reales. Se calcula con
  tokens y PRICING_TABLE. El pricing_fetcher puede actualizar precios desde la web.
- **Nombre de proyecto**: se extrae del campo `cwd` de la primera linea tipo
  `user` (ultimo segmento del path). Fallback: nombre del directorio encoded.

---

## Sistema de gestion de features

Las features futuras se gestionan como archivos Markdown en `docs/private/features/`.

### Estructura

- Un archivo `.md` por feature: `docs/private/features/{NNN}-{slug}.md`
- Plantilla base: `docs/private/features/_template.md`
- Frontmatter YAML con: id, title, status, priority, complexity, created, updated, tags, plan

### Estados

```
idea → draft → analysis → ready → planned → in-progress → done
                                                  ↓
                                              discarded
```

| Estado | Significado |
|--------|------------|
| `idea` | Concepto minimo |
| `draft` | Descripcion completa, sin analisis tecnico |
| `analysis` | Siendo analizada — notas, trade-offs |
| `ready` | Analisis completo, lista para planificar |
| `planned` | Tiene plan de desarrollo en `.claude/plans/` |
| `in-progress` | Siendo implementada |
| `done` | Implementada y mergeada |
| `discarded` | Descartada con razon documentada |

### Operaciones

- **Crear**: copiar `_template.md`, asignar siguiente numero secuencial
- **Listar**: leer directorio, mostrar tabla (id, titulo, status, prioridad)
- **Analizar**: leer feature, investigar viabilidad, agregar notas en seccion Analisis
- **Planificar**: cambiar status a `planned`, generar plan en `.claude/plans/`, linkear en frontmatter `plan:`
- **Implementar**: cambiar status a `in-progress`, seguir el plan
