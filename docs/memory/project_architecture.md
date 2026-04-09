---
name: Arquitectura y modulos
description: Mapa de modulos, responsabilidades y flujo de datos - evita tener que leer todos los archivos para entender la estructura
type: project
---

**Why:** Ahorra tener que explorar la estructura en cada conversacion.

**How to apply:** Consultar antes de hacer cambios para saber que archivos tocar.

## Estructura

```
claude_monitor/
  __init__.py          — package marker
  __main__.py          — entry point (python -m claude_monitor)
  models.py            — 5 dataclasses: TokenUsage, CostEntry, ProjectStats, DailyReport + Session(legacy)
  config.py            — PRICING_TABLE (3 modelos), ConfigManager (lee/escribe ~/.claude-monitor/config.json), constantes
  log_parser.py        — ClaudeLogParser: parsea ~/.claude/projects/**/*.jsonl, deduplica por message.id, calcula costos
  app.py               — ClaudeMonitorApp(rumps.App): menu bar macOS, timer 30s, alertas, daily reset
  cli.py               — CLI formatter: tabla terminal, resumen 7 dias, flag --update-prices
  pricing_fetcher.py   — Scraper HTML de precios desde platform.claude.com, cache 24h en pricing_cache.json

tests/
  conftest.py          — fixtures pytest
  test_models.py       — 7 tests
  test_config.py       — 17 tests
  test_parser.py       — 30 tests
  test_pricing_fetcher.py — 22 tests
  fixtures/            — sample_session.jsonl, sample_subagent.jsonl, empty.jsonl, malformed.jsonl
```

## Flujo de datos

```
~/.claude/projects/**/*.jsonl → log_parser.py → models.py (DailyReport) → app.py (menu bar) / cli.py (terminal)
                                                                         ↑
                                              config.py (pricing, thresholds, persistence)
                                              pricing_fetcher.py (precios actualizados)
```

## Archivos de config del usuario

- `~/.claude-monitor/config.json` — preferencias persistentes (threshold, refresh interval, offsets)
- `~/.claude-monitor/pricing_cache.json` — cache de precios scrapeados
