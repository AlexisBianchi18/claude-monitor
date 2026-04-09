---
name: Testing y fixtures
description: Como correr tests, que cubren, y estructura de fixtures JSONL para agregar nuevos tests
type: project
---

**Why:** Saber como testear rapidamente sin releer conftest.py ni fixtures.

**How to apply:** Usar antes de escribir o modificar tests.

## Ejecutar tests

```bash
uv run pytest tests/ -v
```

76 tests, todos pasan. Sin dependencias externas (todo mockeado).

## Fixtures disponibles

- `tests/fixtures/sample_session.jsonl` — 9 entradas: assistant (opus, sonnet), user, queue-operation, attachment, ai-title, mal formadas
- `tests/fixtures/sample_subagent.jsonl` — sesion de subagente
- `tests/fixtures/empty.jsonl` — archivo vacio
- `tests/fixtures/malformed.jsonl` — JSON invalido

## Patron de test del parser

Los tests usan `tmp_path` de pytest para crear directorios temporales que simulan `~/.claude/projects/`. Se instancia `ClaudeLogParser(logs_dir=tmp_path)` para aislar del filesystem real.

## Edge cases cubiertos

- Dir no existe → reporte vacio sin error
- Lineas mal formadas → ignoradas
- Tipos no-assistant → ignorados
- Modelo synthetic → ignorado
- Deduplicacion por message.id
- Filtrado por fecha (hoy vs ayer)
- Tokens faltantes → default 0
- Config corrupto → defaults
- Alerta se dispara solo 1 vez por dia
