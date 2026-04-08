# Claude Code Cost Monitor

Aplicación para macOS que monitorea en tiempo real el costo y uso de tokens de Claude Code, leyendo los logs locales de `~/.claude/projects/` sin necesidad de API keys.

## Estado actual

**Etapa 3 completada** — App empaquetada como .app standalone para macOS.

| Etapa | Descripción | Estado |
|-------|-------------|--------|
| 1 | Parser + CLI Report | ✅ |
| 2 | App en barra de menú (rumps) | ✅ |
| 3 | Pulido, alertas y empaquetado (.app) | ✅ |

## Qué hace

- Parsea archivos JSONL de `~/.claude/projects/` (sesiones + subagentes)
- Calcula costos por modelo usando tokens × precios públicos
- Deduplica mensajes repetidos por streaming (mismo `message.id`)
- Agrupa por proyecto con nombres legibles extraídos del campo `cwd`
- Filtra por fecha con conversión UTC → zona horaria local

## Requisitos

- Python 3.11+
- macOS 12+
- [uv](https://docs.astral.sh/uv/) (gestor de paquetes)

## Instalación

```bash
# Crear entorno virtual
uv venv

# Instalar dependencias
uv pip install rumps

# Instalar dependencias de desarrollo
uv pip install pytest
```

## Uso

### App en barra de menú (Etapa 2)

```bash
.venv/bin/python -m claude_monitor.app
```

Aparece un icono `C $X.XX` en la barra de menú de macOS. Al hacer click muestra:

- Costo total del día con cantidad de llamadas y tokens
- Desglose por proyecto (hasta 10 proyectos)
- Resumen semanal con promedio diario
- Botón "Refresh Now" para actualizar manualmente
- Botón "Quit" para cerrar

Se auto-refresca cada 30 segundos. Si el costo supera $5.00, el título cambia a `⚠ $X.XX` y envía una notificación de macOS (una vez por día).

Funcionalidades adicionales (Etapa 3):

- **Reset Daily Counter**: Resetea el contador del día a $0.00 (guarda el costo actual como offset)
- **Preferences**: Abre el archivo de configuración `~/.claude-monitor/config.json` con TextEdit
- **Alertas nativas**: Notificación de macOS cuando el costo supera el umbral (configurable)
- **Configuración persistente**: Todos los ajustes se guardan en `~/.claude-monitor/config.json`

### Reporte en terminal

```bash
.venv/bin/python -m claude_monitor.cli
```

Salida ejemplo:

```
============================================================
  Claude Code Cost Report — Wednesday, April 08, 2026
============================================================

  Today's total:  $35.8810
  Total tokens:   11,898,884
  API calls:      337

  Project                              Cost    Calls
  ------------------------------ ---------- -------
  contextual-url-learning          $18.4755      197
  claude-monitor                   $17.4055      140

  Last 7 days:
    Mon 04/06  $20.6719
    Tue 04/07  $2.4660
    Wed 04/08  $35.8810 <-- today
                 --------
         Week  $59.0189  (avg $8.4313/day)
```

### Empaquetar como .app (Etapa 3)

```bash
# Instalar PyInstaller
uv pip install pyinstaller

# Build de producción (standalone)
.venv/bin/python setup.py

# Abrir la app
open dist/Claude\ Monitor.app
```

La app empaquetada (~22 MB):
- No aparece en el Dock (`LSUIElement: true`)
- Es standalone (incluye Python y todas las dependencias)
- Se puede copiar a `/Applications/`

### Configuración

La app guarda su configuración en `~/.claude-monitor/config.json`:

```json
{
  "refresh_interval_seconds": 30,
  "cost_alert_threshold_usd": 5.0,
  "max_projects_in_menu": 10
}
```

Se puede editar desde el menú (Preferences) o manualmente.

## Tests

```bash
# Ejecutar todos los tests
.venv/bin/python -m pytest tests/ -v

# Ejecutar solo tests del parser
.venv/bin/python -m pytest tests/test_parser.py -v

# Ejecutar solo tests de modelos
.venv/bin/python -m pytest tests/test_models.py -v

# Ejecutar solo tests de configuración
.venv/bin/python -m pytest tests/test_config.py -v
```

### Cobertura de tests (50 tests)

- Directorio inexistente → reporte vacío sin error
- Archivos vacíos y líneas JSON malformadas → se ignoran
- Tipos no-assistant (user, queue-operation, attachment, ai-title) → se ignoran
- Modelo `<synthetic>` → se ignora
- Deduplicación por `message.id` → solo cuenta el último
- Cálculo de costo correcto para Opus, Sonnet y Haiku
- Modelo desconocido → costo $0.00
- Filtrado por fecha (ayer excluido, hoy incluido)
- Parsing de timestamps UTC con `Z` y con offset
- Subagentes incluidos desde `<session>/subagents/*.jsonl`
- Nombre de proyecto extraído desde campo `cwd`; fallback al nombre de directorio
- Proyectos ordenados por costo descendente
- Entry sin campo `usage` → se ignora
- Tokens de cache faltantes → default 0
- Directorio `memory/` ignorado
- Archivos `.meta.json` ignorados
- Reporte semanal retorna 7 días ordenados
- ConfigManager crea directorio y archivo si no existen
- Config con JSON corrupto → usa defaults
- Config con JSON array → usa defaults
- Config vacío → usa defaults
- Keys faltantes → merge con defaults
- Keys extra → preservadas
- Daily offset: set, get, persistencia, fechas independientes
- Alert tracking: marcar, verificar, diferente día, persistencia
- Round-trip completo: save + reload

## Estructura del proyecto

```
claude-monitor/
├── claude_monitor/
│   ├── __init__.py
│   ├── __main__.py        # python -m claude_monitor
│   ├── models.py          # Dataclasses: TokenUsage, CostEntry, ProjectStats, DailyReport
│   ├── config.py          # Precios por modelo, constantes, ConfigManager
│   ├── log_parser.py      # ClaudeLogParser: lectura y parsing de JSONL
│   ├── cli.py             # Reporte formateado en terminal
│   └── app.py             # App de barra de menú (rumps) con alertas y reset
├── tests/
│   ├── test_models.py
│   ├── test_parser.py
│   ├── test_config.py
│   └── fixtures/
│       ├── sample_session.jsonl
│       ├── sample_subagent.jsonl
│       ├── malformed.jsonl
│       └── empty.jsonl
├── run_app.py             # Entry point para PyInstaller
├── setup.py               # Build script (PyInstaller → .app)
├── CLAUDE.md              # Especificación del proyecto
├── PLAN.md                # Plan de desarrollo por etapas
├── requirements.txt
└── README.md
```

## Modelos soportados y precios

| Modelo | Input ($/M) | Output ($/M) | Cache Read ($/M) | Cache Create ($/M) |
|--------|-------------|--------------|-------------------|---------------------|
| claude-opus-4-6 | 15.00 | 75.00 | 1.50 | 18.75 |
| claude-sonnet-4-6 | 3.00 | 15.00 | 0.30 | 3.75 |
| claude-haiku-4-5-20251001 | 0.80 | 4.00 | 0.08 | 1.00 |

Los precios se pueden actualizar en [config.py](claude_monitor/config.py).
