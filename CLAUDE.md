# Claude Code Cost Monitor — macOS Menu Bar App

## Objetivo del proyecto

Aplicación Python para macOS que muestra en la barra de menú superior el costo
y uso de tokens de Claude Code en tiempo real, leyendo los logs locales de
`~/.claude/` sin necesidad de ninguna API key.

---

## Stack y dependencias

```
rumps==0.4.0          # menu bar nativa macOS
py2app==0.28.7        # empaquetado como .app
python-dateutil       # parsing de fechas en logs
```

Requiere Python 3.11+ y macOS 12+. Instalar con:

```bash
pip install rumps py2app python-dateutil
```

---

## Estructura del proyecto

```
claude-monitor/
├── CLAUDE.md               ← este archivo
├── app.py                  ← entrada principal (rumps app)
├── log_parser.py           ← lector de ~/.claude/projects/
├── models.py               ← dataclasses: Session, ProjectStats, DailyReport
├── config.py               ← umbrales, intervalo de refresco, preferencias
├── setup.py                ← configuración py2app para generar .app
└── tests/
    ├── test_parser.py
    └── fixtures/
        └── sample.jsonl    ← datos de prueba sin info real
```

---

## Arquitectura

### Flujo de datos

```
~/.claude/projects/**/*.jsonl
        │
        ▼
  log_parser.py          lee y parsea líneas JSONL
        │
        ▼
  models.py              DailyReport con costos y tokens por proyecto
        │
        ▼
  app.py (rumps)         actualiza título y ítems del menú
        │
        ▼
  Barra de macOS         "C $0.42" visible junto a WiFi y batería
```

---

## Módulos a implementar

### 1. `models.py`

Define las siguientes dataclasses:

```python
@dataclass
class Session:
    project: str          # nombre de carpeta del proyecto
    model: str            # ej: claude-opus-4-5
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime

@dataclass
class ProjectStats:
    name: str
    total_cost: float
    total_tokens: int
    session_count: int

@dataclass
class DailyReport:
    date: date
    total_cost: float
    total_tokens: int
    session_count: int
    projects: list[ProjectStats]   # ordenados por costo desc
    weekly_total: float
    daily_average: float
```

### 2. `log_parser.py`

Clase `ClaudeLogParser` con los métodos:

- `get_daily_report(target_date=None) -> DailyReport`
  Parsea todos los `.jsonl` bajo `~/.claude/projects/` filtrando por fecha.
  Si `target_date` es None, usa la fecha de hoy.

- `get_weekly_report() -> list[DailyReport]`
  Retorna los últimos 7 días.

- `_parse_jsonl_file(path: Path) -> list[Session]`
  Lee un archivo `.jsonl` línea a línea. Cada línea es un JSON con esta
  estructura (campos relevantes a extraer):

  ```json
  {
    "type": "assistant",
    "timestamp": "2025-04-08T14:23:11.000Z",
    "model": "claude-opus-4-5",
    "usage": {
      "input_tokens": 1240,
      "output_tokens": 387,
      "cache_read_input_tokens": 0
    },
    "costUSD": 0.0231
  }
  ```

  Ignorar líneas con `"type"` distinto de `"assistant"` o sin campo `"usage"`.
  Ignorar líneas mal formadas (try/except por línea, no abortar el archivo).

- `_project_name_from_path(path: Path) -> str`
  El nombre del proyecto es el nombre de la carpeta inmediatamente bajo
  `~/.claude/projects/`. Ejemplo:
  `~/.claude/projects/mi-api-backend/session-abc.jsonl` → `"mi-api-backend"`

**Importante:** el parser nunca debe fallar si el directorio no existe o está
vacío. Retornar un `DailyReport` con todos los valores en cero.

### 3. `config.py`

```python
REFRESH_INTERVAL_SECONDS = 30
COST_ALERT_THRESHOLD_USD = 1.00   # título cambia a naranja sobre este valor
MAX_PROJECTS_IN_MENU = 5          # mostrar solo los N proyectos más costosos
CLAUDE_LOGS_DIR = Path.home() / ".claude" / "projects"
```

Estos valores se pueden leer/escribir en `~/.claude-monitor/config.json` para
persistencia entre reinicios. Crear el archivo si no existe con los defaults.

### 4. `app.py`

Clase `ClaudeMonitorApp(rumps.App)` que:

**`__init__`:**
- Título inicial: `"C …"` mientras carga
- Construir el menú con estos ítems en orden:
  1. `"Hoy: cargando..."` — resumen del día (no clickeable)
  2. Separador
  3. Hasta `MAX_PROJECTS_IN_MENU` ítems de proyecto, cada uno con formato
     `"  nombre-proyecto   $X.XX"` (alineados con espacios)
  4. Separador
  5. `"Esta semana: $X.XX  (prom. $X.XX/día)"` — no clickeable
  6. Separador
  7. `"Actualizar ahora"` → callback `self.refresh`
  8. `"Resetear contador diario"` → callback `self.reset_daily`
  9. `"Preferencias…"` → callback `self.open_prefs` (abrir config.json con el editor del sistema)
  10. Separador
  11. `"Salir"` → `rumps.quit_application`
- Iniciar `rumps.Timer(self.refresh, REFRESH_INTERVAL_SECONDS)` y llamar
  `self.refresh(None)` de inmediato.

**`refresh(self, sender)`:**
- Llamar `parser.get_daily_report()` y `parser.get_weekly_report()`
- Actualizar `self.title`:
  - Normal: `f"C ${report.total_cost:.2f}"`
  - Alerta (sobre umbral): `f"⚠ ${report.total_cost:.2f}"`
- Actualizar los ítems del menú con los nuevos datos
- Reconstruir dinámicamente los ítems de proyecto (pueden cambiar entre
  reinicios si hay proyectos nuevos)

**`reset_daily(self, sender)`:**
- Mostrar un `rumps.alert` de confirmación antes de actuar
- Guardar en `~/.claude-monitor/overrides.json` la fecha y un offset negativo
  igual al costo actual, de modo que el cálculo del día muestre $0.00
- Llamar `self.refresh(None)` al confirmar

**`open_prefs(self, sender)`:**
- `os.system(f'open -e {config_path}')` para abrir con TextEdit

**`main()`:**
- Instanciar y correr `ClaudeMonitorApp().run()`

### 5. `setup.py`

Configuración mínima para `py2app`:

```python
from setuptools import setup

APP = ['app.py']
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'LSUIElement': True,        # no aparece en el Dock
        'CFBundleName': 'Claude Monitor',
        'CFBundleVersion': '1.0.0',
    },
    'packages': ['rumps', 'dateutil'],
}

setup(app=APP, options={'py2app': OPTIONS})
```

Construir con: `python setup.py py2app`

---

## Orden de implementación

Seguir este orden exacto para poder probar de forma incremental:

1. `models.py` — sin dependencias externas, testeable de inmediato
2. `config.py` — leer/escribir JSON, sin dependencias externas
3. `log_parser.py` + `tests/test_parser.py` con el fixture `sample.jsonl`
4. `app.py` — integrar parser y config, probar en vivo con `python app.py`
5. `setup.py` — solo después de que todo funcione en desarrollo

---

## Tests

En `tests/test_parser.py` cubrir los siguientes casos:

- Directorio `~/.claude/projects/` no existe → retorna reporte vacío sin error
- Archivo `.jsonl` con líneas mal formadas → se ignoran sin abortar
- Líneas de tipo `"user"` → se ignoran correctamente
- Cálculo correcto de costo total sumando múltiples archivos
- Agrupación correcta por nombre de proyecto
- Filtrado por fecha: sesiones de ayer no aparecen en el reporte de hoy

El fixture `tests/fixtures/sample.jsonl` debe incluir al menos:
- 3 sesiones de hoy en 2 proyectos distintos
- 2 sesiones de ayer
- 1 línea mal formada
- 1 línea de tipo `"user"`

---

## Notas importantes

- **Nunca leer archivos fuera de `~/.claude/`**. El parser no debe aceptar
  rutas arbitrarias.
- **Sin llamadas de red**. Todo el cálculo es local. No usar la Anthropic API.
- **Thread safety**: `rumps.Timer` corre en el hilo principal. El parser es
  síncrono y suficientemente rápido para los volúmenes esperados (< 10k líneas).
  Si en el futuro se necesita async, usar `threading.Thread` y actualizar la UI
  solo desde el callback del Timer.
- **Privacidad**: los logs pueden contener prompts. La app solo lee campos
  numéricos (`usage`, `costUSD`, `timestamp`, `model`). No leer ni exponer
  el campo `content` de ninguna línea.
- El campo `costUSD` puede no estar presente en versiones viejas de Claude Code.
  En ese caso, calcular el costo aproximado usando los tokens y los precios
  públicos del modelo. Definir una tabla de precios en `config.py`.