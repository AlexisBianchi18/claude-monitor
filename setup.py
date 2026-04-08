"""Empaquetado de Claude Monitor como .app para macOS usando PyInstaller."""

import subprocess
import sys


def build():
    """Construye Claude Monitor.app usando PyInstaller."""
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", "Claude Monitor",
        "--windowed",                    # .app bundle (no consola)
        "--onedir",                      # directorio con dependencias
        "--noconfirm",                   # sobreescribir sin preguntar
        "--clean",                       # limpiar cache
        "--osx-bundle-identifier", "com.claude.monitor",
        "--hidden-import", "rumps",
        "--hidden-import", "claude_monitor",
        "--collect-submodules", "claude_monitor",
        "run_app.py",
    ]
    subprocess.run(cmd, check=True)

    # Parchear Info.plist para que no aparezca en el Dock
    plist_path = "dist/Claude Monitor.app/Contents/Info.plist"
    _patch_plist(plist_path)
    print("\n✅ Build completado: dist/Claude Monitor.app")


def _patch_plist(plist_path: str) -> None:
    """Agrega LSUIElement=true al Info.plist para ocultar del Dock."""
    subprocess.run(
        [
            "/usr/libexec/PlistBuddy",
            "-c", "Add :LSUIElement bool true",
            plist_path,
        ],
        check=False,  # falla si ya existe; ignorar
    )
    # Si ya existía, asegurar que esté en true
    subprocess.run(
        [
            "/usr/libexec/PlistBuddy",
            "-c", "Set :LSUIElement true",
            plist_path,
        ],
        check=True,
    )


if __name__ == "__main__":
    build()
