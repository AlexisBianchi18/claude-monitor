---
name: Patrones clave de implementacion
description: Decisiones tecnicas criticas - deduplicacion, calculo de costo, formato de logs JSONL, descubrimiento de sesiones
type: project
---

**Why:** Estas decisiones no son obvias del spec y se descubrieron durante la implementacion. Evita re-descubrirlas.

**How to apply:** Consultar antes de modificar log_parser.py o config.py.

## Formato real de logs (difiere del spec)

El spec asumia campos a nivel raiz, pero en realidad estan anidados:
```json
{"type": "assistant", "message": {"id": "msg_xxx", "model": "claude-opus-4-6", "usage": {...}}}
```
- `model` y `usage` estan bajo `message`, NO en la raiz
- `costUSD` NO existe en los logs reales — se calcula con la pricing table

## Deduplicacion

Streaming genera multiples lineas con el mismo `message.id`. El parser usa `entries_by_id[msg_id] = entry` (last wins) para deduplicar.

## Calculo de costo (por millon de tokens)

```
cost = (input * price_input + output * price_output + cache_read * price_cache_read
        + cache_5m * price_5m + cache_1h * price_1h) / 1_000_000
```

## Precios actuales (abril 2026)

| Modelo | Input | Output | Cache Read | Cache 5m | Cache 1h |
|--------|-------|--------|------------|----------|----------|
| claude-opus-4-6 | $5.00 | $25.00 | $0.50 | $6.25 | $10.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| claude-haiku-4-5 | $1.00 | $5.00 | $0.10 | $1.25 | $2.00 |

## Descubrimiento de archivos

- Busca `*.jsonl` en `~/.claude/projects/<project-dir>/`
- Tambien busca subagentes: `<session-uuid>/subagents/agent-*.jsonl`
- Ignora: directorio `memory/`, archivos `.meta.json`, modelo `<synthetic>`

## Nombre de proyecto

1. Busca primera linea tipo `user` con campo `cwd`
2. Extrae ultimo segmento: `/Users/user/Projects/my-app` → `my-app`
3. Fallback: nombre del directorio encoded (ej: `-Users-user-Projects-my-app`)
