"""Tests para claude_monitor.updater."""

from __future__ import annotations

import io
import json
import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from claude_monitor.updater import (
    _is_newer,
    check_for_update,
    detect_app_path,
    download_and_replace,
    get_update_info,
    reset_update_state,
)


# --- TestIsNewer ---


class TestIsNewer:
    def test_newer_major(self):
        assert _is_newer("2.0.0", "1.0.0") is True

    def test_newer_minor(self):
        assert _is_newer("1.1.0", "1.0.0") is True

    def test_newer_patch(self):
        assert _is_newer("1.0.1", "1.0.0") is True

    def test_same_version(self):
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_older_major(self):
        assert _is_newer("0.9.0", "1.0.0") is False

    def test_older_minor(self):
        assert _is_newer("1.0.0", "1.1.0") is False

    def test_invalid_remote(self):
        assert _is_newer("abc", "1.0.0") is False

    def test_invalid_local(self):
        assert _is_newer("1.0.0", "xyz") is False

    def test_empty_strings(self):
        assert _is_newer("", "") is False


# --- TestCheckForUpdate ---


def _make_github_response(tag: str, asset_name: str, asset_url: str) -> bytes:
    """Crea un JSON simulando la respuesta de GitHub API."""
    data = {
        "tag_name": tag,
        "assets": [
            {"name": asset_name, "browser_download_url": asset_url},
        ],
    }
    return json.dumps(data).encode("utf-8")


class TestCheckForUpdate:
    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_newer_version_available(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = _make_github_response(
            "v1.1.0", "Claude.Monitor.app.zip", "https://example.com/app.zip"
        )
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        version, url = check_for_update()
        assert version == "1.1.0"
        assert url == "https://example.com/app.zip"

    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_same_version(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = _make_github_response(
            "v1.0.0", "Claude.Monitor.app.zip", "https://example.com/app.zip"
        )
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        version, url = check_for_update()
        assert version is None
        assert url is None

    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_older_version(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = _make_github_response(
            "v0.9.0", "Claude.Monitor.app.zip", "https://example.com/app.zip"
        )
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        version, url = check_for_update()
        assert version is None
        assert url is None

    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("Connection refused")

        version, url = check_for_update()
        assert version is None
        assert url is None

        _, _, error = get_update_info()
        assert "Connection refused" in error

    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_missing_asset(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = _make_github_response(
            "v2.0.0", "other-file.tar.gz", "https://example.com/other.tar.gz"
        )
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        version, url = check_for_update()
        assert version is None
        assert url is None

    @patch("claude_monitor.updater.__version__", "1.0.0")
    @patch("claude_monitor.updater.urllib.request.urlopen")
    def test_update_info_cached(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = _make_github_response(
            "v1.2.0", "Claude.Monitor.app.zip", "https://example.com/app.zip"
        )
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        check_for_update()
        version, url, error = get_update_info()
        assert version == "1.2.0"
        assert url == "https://example.com/app.zip"
        assert error is None

    def test_get_update_info_initial_state(self):
        version, url, error = get_update_info()
        assert version is None
        assert url is None
        assert error is None

    def test_reset_clears_state(self):
        # Simulo estado seteado manualmente
        import claude_monitor.updater as mod
        mod._latest_version = "2.0.0"
        mod._download_url = "https://example.com"
        mod._update_error = "test error"

        reset_update_state()
        version, url, error = get_update_info()
        assert version is None
        assert url is None
        assert error is None


# --- TestDetectAppPath ---


class TestDetectAppPath:
    def test_running_from_source(self):
        """Sin sys.frozen, retorna None."""
        assert detect_app_path() is None

    @patch("claude_monitor.updater.sys")
    def test_running_as_app(self, mock_sys):
        mock_sys.frozen = True
        mock_sys.executable = "/Applications/Claude Monitor.app/Contents/MacOS/Claude Monitor"

        result = detect_app_path()
        assert result == "/Applications/Claude Monitor.app"

    @patch("claude_monitor.updater.sys")
    def test_non_app_frozen_path(self, mock_sys):
        mock_sys.frozen = True
        mock_sys.executable = "/usr/local/bin/claude-monitor"

        result = detect_app_path()
        assert result is None


# --- TestDownloadAndReplace ---


def _create_fake_app(base_dir: str, app_name: str = "Claude Monitor.app") -> str:
    """Crea una estructura .app falsa para tests."""
    app_path = os.path.join(base_dir, app_name)
    macos_dir = os.path.join(app_path, "Contents", "MacOS")
    os.makedirs(macos_dir)

    # Info.plist
    plist_path = os.path.join(app_path, "Contents", "Info.plist")
    with open(plist_path, "w") as f:
        f.write("<plist></plist>")

    # Executable falso
    exe_path = os.path.join(macos_dir, "Claude Monitor")
    with open(exe_path, "w") as f:
        f.write("#!/bin/sh\necho hello")

    return app_path


def _create_app_zip(base_dir: str, app_name: str = "Claude Monitor.app") -> str:
    """Crea un .zip que contiene un .app falso."""
    app_path = _create_fake_app(base_dir, app_name)
    zip_path = os.path.join(base_dir, "update.zip")

    with zipfile.ZipFile(zip_path, "w") as zf:
        for root, dirs, files in os.walk(app_path):
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.relpath(full, base_dir)
                zf.write(full, arcname)

    return zip_path


class TestDownloadAndReplace:
    def test_successful_replacement(self, tmp_path):
        # App actual
        current_app = _create_fake_app(str(tmp_path / "installed"))

        # Zip con nueva versión
        new_dir = str(tmp_path / "new")
        os.makedirs(new_dir)
        zip_path = _create_app_zip(new_dir)

        # Mock urlretrieve para copiar el zip local
        def fake_retrieve(url, dest):
            import shutil
            shutil.copy2(zip_path, dest)
            return dest, {}

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            with patch("claude_monitor.updater.subprocess.run"):
                error = download_and_replace("https://fake.url/app.zip", current_app)

        assert error is None
        assert os.path.isdir(current_app)
        assert os.path.isfile(os.path.join(current_app, "Contents", "Info.plist"))

    def test_invalid_zip(self, tmp_path):
        current_app = _create_fake_app(str(tmp_path / "installed"))

        # Crear un archivo que no es zip
        bad_zip = str(tmp_path / "bad.zip")
        with open(bad_zip, "w") as f:
            f.write("not a zip")

        def fake_retrieve(url, dest):
            import shutil
            shutil.copy2(bad_zip, dest)
            return dest, {}

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            error = download_and_replace("https://fake.url/app.zip", current_app)

        assert error is not None
        assert "Update failed" in error
        # La app original debe seguir existiendo
        assert os.path.isdir(current_app)

    def test_no_app_in_zip(self, tmp_path):
        current_app = _create_fake_app(str(tmp_path / "installed"))

        # Zip sin .app dentro
        zip_path = str(tmp_path / "empty.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no app here")

        def fake_retrieve(url, dest):
            import shutil
            shutil.copy2(zip_path, dest)
            return dest, {}

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            error = download_and_replace("https://fake.url/app.zip", current_app)

        assert error == "No .app bundle found in downloaded archive"
        assert os.path.isdir(current_app)

    def test_invalid_app_structure(self, tmp_path):
        current_app = _create_fake_app(str(tmp_path / "installed"))

        # Zip con .app que no tiene Contents/MacOS
        bad_app_dir = str(tmp_path / "bad_new")
        os.makedirs(bad_app_dir)
        fake_app = os.path.join(bad_app_dir, "Bad.app")
        os.makedirs(fake_app)
        zip_path = os.path.join(bad_app_dir, "bad.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("Bad.app/something.txt", "fake")

        def fake_retrieve(url, dest):
            import shutil
            shutil.copy2(zip_path, dest)
            return dest, {}

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            error = download_and_replace("https://fake.url/app.zip", current_app)

        assert error == "Downloaded .app has invalid structure"
        assert os.path.isdir(current_app)

    def test_permission_error(self, tmp_path):
        current_app = _create_fake_app(str(tmp_path / "installed"))

        def fake_retrieve(url, dest):
            raise PermissionError("Access denied")

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            error = download_and_replace("https://fake.url/app.zip", current_app)

        assert "Permission denied" in error

    def test_restore_on_move_failure(self, tmp_path):
        current_app = _create_fake_app(str(tmp_path / "installed"))

        # Zip válido
        new_dir = str(tmp_path / "new")
        os.makedirs(new_dir)
        zip_path = _create_app_zip(new_dir)

        def fake_retrieve(url, dest):
            import shutil
            shutil.copy2(zip_path, dest)
            return dest, {}

        def failing_move(src, dst):
            raise OSError("Disk full")

        with patch("claude_monitor.updater.urllib.request.urlretrieve", fake_retrieve):
            with patch("claude_monitor.updater.subprocess.run"):
                with patch("claude_monitor.updater.shutil.move", failing_move):
                    error = download_and_replace("https://fake.url/app.zip", current_app)

        assert error is not None
        # La app original debe haber sido restaurada
        assert os.path.isdir(current_app)
