"""Auto-update via GitHub Releases para Claude Monitor."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import __version__

logger = logging.getLogger(__name__)

GITHUB_API_URL = (
    "https://api.github.com/repos/SirMatoran/claude-monitor/releases/latest"
)
GITHUB_API_TIMEOUT = 15
UPDATE_ASSET_NAME = "Claude.Monitor.app.zip"

# Estado del módulo (cache entre checks)
_latest_version: str | None = None
_download_url: str | None = None
_update_error: str | None = None


def _is_newer(remote: str, local: str) -> bool:
    """True si la versión remota es estrictamente mayor que la local."""
    try:
        r = tuple(int(x) for x in remote.split("."))
        l = tuple(int(x) for x in local.split("."))  # noqa: E741
        return r > l
    except (ValueError, TypeError):
        return False


def check_for_update() -> tuple[str | None, str | None]:
    """Chequea GitHub API por nueva versión.

    Retorna (version, download_url) si hay update, o (None, None).
    """
    global _latest_version, _download_url, _update_error

    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"claude-monitor/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        version = tag.lstrip("v")

        if not _is_newer(version, __version__):
            _latest_version = None
            _download_url = None
            _update_error = None
            return None, None

        # Buscar el asset .zip
        url = None
        for asset in data.get("assets", []):
            if asset.get("name") == UPDATE_ASSET_NAME:
                url = asset.get("browser_download_url")
                break

        if not url:
            _update_error = f"Release v{version} found but no {UPDATE_ASSET_NAME} asset"
            logger.warning(_update_error)
            return None, None

        _latest_version = version
        _download_url = url
        _update_error = None
        return version, url

    except Exception as exc:
        _update_error = str(exc)
        logger.warning("Update check failed: %s", exc)
        return None, None


def get_update_info() -> tuple[str | None, str | None, str | None]:
    """Retorna el estado cacheado: (version, url, error)."""
    return _latest_version, _download_url, _update_error


def detect_app_path() -> str | None:
    """Retorna el path al .app bundle si corre como app empaquetada, o None."""
    if not getattr(sys, "frozen", False):
        return None
    # sys.executable: .../Claude Monitor.app/Contents/MacOS/Claude Monitor
    macos_dir = os.path.dirname(sys.executable)
    contents_dir = os.path.dirname(macos_dir)
    app_dir = os.path.dirname(contents_dir)
    if app_dir.endswith(".app"):
        return app_dir
    return None


def download_and_replace(download_url: str, current_app_path: str) -> str | None:
    """Descarga el .app.zip, reemplaza el .app actual.

    Retorna None si todo OK, o un string con el error.
    """
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="claude-monitor-update-")
        zip_path = os.path.join(temp_dir, "update.zip")

        # Descargar
        urllib.request.urlretrieve(download_url, zip_path)

        # Extraer
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)

        # Buscar el .app extraído
        extracted_app = None
        for entry in os.listdir(temp_dir):
            if entry.endswith(".app"):
                extracted_app = os.path.join(temp_dir, entry)
                break

        if not extracted_app:
            return "No .app bundle found in downloaded archive"

        # Verificar estructura básica
        contents_macos = os.path.join(extracted_app, "Contents", "MacOS")
        contents_plist = os.path.join(extracted_app, "Contents", "Info.plist")
        if not os.path.isdir(contents_macos) or not os.path.isfile(contents_plist):
            return "Downloaded .app has invalid structure"

        # Limpiar quarantine de macOS
        subprocess.run(
            ["xattr", "-cr", extracted_app],
            check=False,
            capture_output=True,
        )

        # Reemplazo atómico
        old_path = current_app_path + ".old"
        os.rename(current_app_path, old_path)
        try:
            shutil.move(extracted_app, current_app_path)
        except Exception:
            # Restaurar si falla el move
            os.rename(old_path, current_app_path)
            raise
        shutil.rmtree(old_path, ignore_errors=True)

        return None

    except PermissionError:
        return (
            "Permission denied. Move the app to ~/Applications/ "
            "or check file permissions."
        )
    except Exception as exc:
        return f"Update failed: {exc}"
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def restart_app(app_path: str) -> None:
    """Lanza el nuevo ejecutable y termina el proceso actual."""
    executable = os.path.join(app_path, "Contents", "MacOS", "Claude Monitor")
    subprocess.Popen([executable])
    sys.exit(0)


def reset_update_state() -> None:
    """Limpia el estado del módulo (para tests)."""
    global _latest_version, _download_url, _update_error
    _latest_version = None
    _download_url = None
    _update_error = None
