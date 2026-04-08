---
name: Build y distribucion
description: Como empaquetar la app como .app de macOS con PyInstaller y como ejecutar en desarrollo
type: project
---

**Why:** Los comandos de build no son obvios y el spec original usaba py2app pero se migro a PyInstaller.

**How to apply:** Consultar cuando se necesite empaquetar o ejecutar la app.

## Desarrollo

```bash
uv run python -m claude_monitor        # menu bar app
uv run python -m claude_monitor.cli    # reporte en terminal
uv run python -m claude_monitor.cli --update-prices  # actualizar precios
```

## Build (.app)

Se usa PyInstaller (NO py2app como decia el spec original):

```bash
uv run python setup.py  # wrapper que invoca PyInstaller
```

`setup.py` genera un bundle .app con `LSUIElement=True` (no aparece en Dock).

## Dependencias (requirements.txt)

```
rumps>=0.4.0
pyinstaller>=6.0
pytest>=7.0
```

Python 3.11+, macOS 12+. Sin python-dateutil (se usa fromisoformat nativo de 3.11).
