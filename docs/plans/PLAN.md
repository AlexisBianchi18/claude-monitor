# Plan: Claude Code Cost Monitor — macOS Menu Bar App

## Contexto

El usuario necesita monitorear en tiempo real cuánto gasta en Claude Code. La app lee los logs locales de `~/.claude/projects/` y muestra el costo en la barra de menú de macOS. No requiere API keys ni llamadas de red.

**Diferencias críticas entre CLAUDE.md y la realidad de los logs:**
- No existe campo `costUSD` → calcular desde tokens × precios
- `model` está en `message.model`, no a nivel raíz
- `usage` está en `message.usage`, no a nivel raíz
- Hay tokens de cache: `cache_creation_input_tokens`, `cache_read_input_tokens`
- Los `message.id` aparecen duplicados (streaming) → deduplicar quedándose con el último
- Modelo `<synthetic>` tiene tokens en cero → ignorar
- Directorios de proyecto codificados: `-Users-user-Projects-foo` → extraer último segmento
- Subagentes en `<session-uuid>/subagents/agent-*.jsonl`
- `python-dateutil` no es necesario — Python 3.11+ `datetime.fromisoformat()` basta

## Estructura del proyecto

```
claude-monitor/
  claude_monitor/
    __init__.py
    models.py          ← Etapa 1
    config.py          ← Etapa 1 (base) + Etapa 3 (persistencia)
    log_parser.py      ← Etapa 1
    cli.py             ← Etapa 1
    app.py             ← Etapa 2 + Etapa 3
  tests/
    __init__.py
    test_models.py     ← Etapa 1
    test_parser.py     ← Etapa 1
    test_config.py     ← Etapa 3
    fixtures/
      sample_session.jsonl
      sample_subagent.jsonl
      malformed.jsonl
      empty.jsonl
  setup.py             ← Etapa 3
  requirements.txt     ← Etapa 1
```

---

## Etapa 1: Parser + Reporte en Terminal

**Objetivo:** `python -m claude_monitor.cli` imprime los costos reales del día desde los logs.

### 1.1 — `claude_monitor/models.py`

Dataclasses sin dependencias externas:

```python
@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    
    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens 
                + self.cache_read_input_tokens + self.cache_creation_input_tokens)

@dataclass
class CostEntry:
    message_id: str
    model: str
    usage: TokenUsage
    cost_usd: float
    timestamp: datetime  # UTC-aware

@dataclass
class ProjectStats:
    name: str             # último segmento del path
    display_name: str     # con desambiguación si hay colisión
    dir_name: str         # nombre codificado original del directorio
    total_cost: float = 0.0
    total_tokens: int = 0
    entry_count: int = 0

@dataclass
class DailyReport:
    date: date
    total_cost: float = 0.0
    total_tokens: int = 0
    entry_count: int = 0
    projects: list[ProjectStats] = field(default_factory=list)  # ordenados por costo desc
```

### 1.2 — `claude_monitor/config.py`

```python
CLAUDE_LOGS_DIR = Path.home() / ".claude" / "projects"

@dataclass(frozen=True)
class ModelPricing:
    input: float       # $/M tokens
    output: float
    cache_read: float
    cache_create: float

PRICING_TABLE = {
    "claude-opus-4-6":            ModelPricing(15.0, 75.0, 1.50, 18.75),
    "claude-sonnet-4-6":          ModelPricing(3.0, 15.0, 0.30, 3.75),
    "claude-haiku-4-5-20251001":  ModelPricing(0.80, 4.0, 0.08, 1.0),
}

SKIP_MODELS = {"<synthetic>"}
BILLABLE_TYPE = "assistant"

# Constantes para Etapa 2+
REFRESH_INTERVAL_SECONDS = 30
COST_ALERT_THRESHOLD_USD = 5.00
MAX_PROJECTS_IN_MENU = 10
CONFIG_DIR = Path.home() / ".claude-monitor"
```

### 1.3 — `claude_monitor/log_parser.py`

Clase `ClaudeLogParser`:

- **`__init__(self, logs_dir=None)`** — acepta override para tests
- **`get_daily_report(self, target_date=None) -> DailyReport`** — reporte de un día (default: hoy)
- **`_parse_project(self, project_dir, target_date) -> ProjectStats`** — parsea un proyecto completo
- **`_parse_jsonl_file(self, path, target_date) -> list[CostEntry]`** — parsea un archivo con deduplicación
- **`_find_session_files(self, project_dir) -> list[Path]`** — busca `*.jsonl` + `*/subagents/*.jsonl`
- **`_extract_project_name(self, project_dir) -> tuple[str, str]`** — lee `cwd` del primer `user` entry
- **`_calculate_cost(model, usage) -> float`** — (estático) tokens × precios / 1M
- **`_parse_timestamp(ts_str) -> datetime`** — (estático) reemplaza `Z` por `+00:00`, usa `fromisoformat()`
- **`_timestamp_to_local_date(dt) -> date`** — (estático) convierte UTC a fecha local

**Deduplicación (el punto más crítico):**
```
entries_by_id = {}
for line in file:
    if type == "assistant" and message.id exists:
        entries_by_id[message.id] = obj  # siempre sobreescribe → el último gana
```

**Búsqueda de archivos:**
```
project_dir/*.jsonl                           ← sesiones principales
project_dir/<uuid>/subagents/agent-*.jsonl    ← subagentes
(ignorar: memory/, *.meta.json)
```

**Extracción de nombre de proyecto:**
1. Leer `cwd` del primer entry tipo `user` en cualquier `.jsonl`
2. `os.path.basename(cwd)` → nombre legible
3. Fallback: usar el nombre codificado del directorio

### 1.4 — `claude_monitor/cli.py`

Función `main()` que:
1. Instancia `ClaudeLogParser()`
2. Obtiene `get_daily_report(today)`
3. Imprime reporte formateado con costos por proyecto
4. Imprime resumen de últimos 7 días

**Salida esperada:**
```
==================================================
  Claude Code Cost Report — Wednesday, April 08, 2026
==================================================

  Today's total:  $4.2382
  Total tokens:   187,432
  API calls:      69

  Project                        Cost      Calls
  ------------------------------ ---------- -------
  claude-monitor                 $  4.2382      69

  Last 7 days:
    Thu 04/02  $0.0000
    ...
    Wed 04/08  $4.2382 <-- today
               --------
         Week  $25.3492  (avg $3.6213/day)
```

### 1.5 — Tests y fixtures

**Fixture `sample_session.jsonl` debe incluir:**
1. Entry `queue-operation` (ignorar)
2. Entry `user` con campo `cwd` (para extracción de nombre)
3. Entry `attachment` (ignorar)
4. Dos entries `assistant` con **mismo** `message.id` (test deduplicación)
5. Entry `assistant` con modelo `claude-opus-4-6`
6. Entry `assistant` con modelo `<synthetic>` (ignorar)
7. Entry `assistant` de ayer (filtrar por fecha)
8. Línea JSON malformada
9. Entry `ai-title` (ignorar)
10. Entry `assistant` sin campo `usage` (ignorar gracefully)

**Tests clave en `test_parser.py`:**
- Directorio inexistente → reporte vacío sin error
- Líneas malformadas → se ignoran
- Tipos no-assistant → se ignoran
- Modelo `<synthetic>` → se ignora
- Deduplicación por `message.id` → solo cuenta el último
- Cálculo de costo correcto para cada modelo (opus, sonnet, haiku)
- Modelo desconocido → costo $0.00
- Filtrado por fecha (ayer excluido, hoy incluido)
- Boundary de timezone UTC/local
- Subagentes incluidos
- Nombre de proyecto desde `cwd`
- Proyectos ordenados por costo descendente
- Campo `usage` faltante → skip graceful
- Tokens individuales faltantes → default 0
- `.meta.json` ignorados
- Directorio `memory/` ignorado

### 1.6 — Verificación Etapa 1

```bash
# Tests
python -m pytest tests/ -v

# Reporte real
python -m claude_monitor.cli

# Validación manual: comparar costo de una sesión conocida
```

---

## Etapa 2: App en Barra de Menú (rumps)

**Objetivo:** Icono `C $4.24` en la barra de menú de macOS con menú desplegable.

### 2.1 — `claude_monitor/app.py`

Clase `ClaudeMonitorApp(rumps.App)`:

**`__init__`:**
- Título inicial: `"C …"`
- Menú: today_item → separador → project_items → separador → week_item → separador → Refresh Now → separador → Quit
- Timer `rumps.Timer(self.on_refresh_timer, 30)` + refresh inmediato

**`_refresh(self)`:**
1. `parser.get_daily_report(today)` para hoy
2. Calcular total semanal (7 llamadas a `get_daily_report`)
3. Actualizar título: `f"C ${cost:.2f}"` o `f"⚠ ${cost:.2f}"` si supera umbral
4. Actualizar items de proyecto dinámicamente
5. Reconstruir menú con `_rebuild_menu()`
6. Try/except global → mostrar `"C err"` si falla

**`_rebuild_menu(self)`:**
- `self.menu.clear()` + reconstruir con items actuales

**`on_refresh_clicked(self, sender)`** — refresh manual
**`on_quit(self, sender)`** — `rumps.quit_application()`

**Menú esperado al hacer click:**
```
Today: $4.24  (69 calls, 187,432 tokens)
────────────────────────
  claude-monitor            $4.24
────────────────────────
This week: $25.35  (avg $3.62/day)
────────────────────────
Refresh Now
────────────────────────
Quit
```

### 2.2 — Verificación Etapa 2

```bash
pip install rumps
python -m claude_monitor.app
# Verificar: aparece en barra de menú, click muestra datos, auto-refresh cada 30s
```

---

## Etapa 3: Pulido y Empaquetado

**Objetivo:** App `.app` producción con alertas, reset, config persistente, py2app.

### 3.1 — `ConfigManager` en `config.py`

Clase para persistir configuración en `~/.claude-monitor/config.json`:
- `load()` / `save()` — JSON en disco
- `get_daily_offset(date)` / `set_daily_offset(date, offset)` — para reset de contador
- `has_alert_fired_today()` / `mark_alert_fired(date)` — evitar alertas repetidas
- Manejo de JSON corrupto → reemplazar con defaults

### 3.2 — Mejoras a `app.py`

- **Alertas:** `rumps.notification()` cuando costo supera umbral (una vez por día)
- **Reset diario:** Dialogo de confirmación + guardar offset en config
- **Preferencias:** Abrir `config.json` con `open -e` + reload después de 5s
- **Costo con offset:** `display_cost = max(0.0, real_cost - offset)`

**Menú final:**
```
Today: $4.24  (69 calls, 187,432 tokens)
────────────────────────
  claude-monitor            $4.24
────────────────────────
This week: $25.35  (avg $3.62/day)
────────────────────────
Refresh Now
Reset Daily Counter
Preferences...
────────────────────────
Quit
```

### 3.3 — `setup.py`

```python
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'LSUIElement': True,
        'CFBundleName': 'Claude Monitor',
        'CFBundleIdentifier': 'com.claude.monitor',
        'CFBundleVersion': '1.0.0',
    },
    'packages': ['claude_monitor'],
    'includes': ['rumps', 'json', 'pathlib', 'dataclasses'],
}
```

### 3.4 — Tests Etapa 3

- `test_config.py`: creación de dir/archivo, persistencia, offsets por fecha, tracking de alertas, JSON corrupto, merge con defaults

### 3.5 — Verificación Etapa 3

```bash
python -m pytest tests/ -v
python -m claude_monitor.app  # verificar alertas, reset, preferencias
python setup.py py2app -A     # build desarrollo
python setup.py py2app        # build producción
open dist/Claude\ Monitor.app # verificar .app standalone
```

---

## Edge Cases (referencia rápida)

| Caso | Manejo | Etapa |
|------|--------|-------|
| `~/.claude/projects/` no existe | Reporte vacío | 1 |
| JSON malformado | Skip línea | 1 |
| `message.id` duplicado (streaming) | Quedarse con el último | 1 |
| Modelo `<synthetic>` | Ignorar | 1 |
| Modelo desconocido | Costo $0, contar tokens | 1 |
| Timestamps UTC vs fecha local | Convertir a local | 1 |
| `usage` faltante | Skip entry | 1 |
| Tokens individuales faltantes | Default 0 | 1 |
| `.meta.json` / `memory/` | Ignorar | 1 |
| Excepción en refresh | Try/except, mostrar "C err" | 2 |
| Config JSON corrupto | Reemplazar con defaults | 3 |
| Alerta repetida mismo día | Track en config | 3 |
| Reset mayor que costo | `max(0.0, cost - offset)` | 3 |

## Archivos críticos a modificar

- `claude_monitor/models.py` — contrato de datos entre todas las capas
- `claude_monitor/config.py` — precios y constantes (E1), `ConfigManager` (E3)
- `claude_monitor/log_parser.py` — motor de parsing, deduplicación, cálculo de costos
- `claude_monitor/cli.py` — reporte en terminal
- `claude_monitor/app.py` — aplicación rumps (E2 + E3)
- `tests/test_parser.py` — validación de todos los edge cases del parser
- `setup.py` — empaquetado py2app (E3)
