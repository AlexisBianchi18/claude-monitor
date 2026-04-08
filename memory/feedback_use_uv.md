---
name: Usar uv para Python
description: Siempre usar uv en lugar de pip/python para gestion de dependencias y entornos virtuales
type: feedback
---

Usar `uv` en lugar de `pip` y `python` para todo lo relacionado con Python: crear entornos virtuales, instalar dependencias, ejecutar scripts y tests.

**Why:** Preferencia explicita del usuario. uv es mas rapido y moderno que pip.

**How to apply:** `uv venv` para crear entornos, `uv pip install` para instalar, `uv run` para ejecutar scripts/tests. Nunca usar `pip install` directamente.
