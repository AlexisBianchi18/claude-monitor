"""Tests para el check de versión via Homebrew en app.py."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_monitor.app import ClaudeMonitorApp


class TestIsNewer:
    """Tests para ClaudeMonitorApp._is_newer."""

    def test_newer_patch(self):
        assert ClaudeMonitorApp._is_newer("1.3.2", "1.3.1") is True

    def test_newer_minor(self):
        assert ClaudeMonitorApp._is_newer("1.4.0", "1.3.1") is True

    def test_newer_major(self):
        assert ClaudeMonitorApp._is_newer("2.0.0", "1.3.1") is True

    def test_same_version(self):
        assert ClaudeMonitorApp._is_newer("1.3.1", "1.3.1") is False

    def test_older_version(self):
        assert ClaudeMonitorApp._is_newer("1.3.0", "1.3.1") is False

    def test_invalid_remote(self):
        assert ClaudeMonitorApp._is_newer("abc", "1.3.1") is False

    def test_empty_remote(self):
        assert ClaudeMonitorApp._is_newer("", "1.3.1") is False

    def test_none_remote(self):
        assert ClaudeMonitorApp._is_newer(None, "1.3.1") is False


class TestCheckBrewUpdate:
    """Tests para ClaudeMonitorApp._check_brew_update."""

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value=None)
    @patch("claude_monitor.app.os.path.isfile", return_value=False)
    def test_no_brew_shows_fallback(self, mock_isfile, mock_which, mock_rumps):
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        assert "Homebrew not found" in call_kwargs.kwargs.get("message", call_kwargs[1].get("message", ""))

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run")
    @patch("claude_monitor.app.__version__", "1.3.0")
    def test_update_available(self, mock_run, mock_which, mock_rumps):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"casks": [{"version": "1.4.0"}]}),
        )
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        assert "1.4.0" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))
        msg = call_kwargs.kwargs.get("message", call_kwargs[1].get("message", ""))
        assert "brew upgrade claude-monitor" in msg

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run")
    @patch("claude_monitor.app.__version__", "1.4.0")
    def test_up_to_date(self, mock_run, mock_which, mock_rumps):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"casks": [{"version": "1.4.0"}]}),
        )
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        assert "Up to Date" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run")
    def test_brew_command_fails(self, mock_run, mock_which, mock_rumps):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Error: Cask not found",
        )
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        msg = call_kwargs.kwargs.get("message", call_kwargs[1].get("message", ""))
        assert "Could not check" in msg

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run", side_effect=subprocess.TimeoutExpired("brew", 30))
    def test_brew_timeout(self, mock_run, mock_which, mock_rumps):
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        msg = call_kwargs.kwargs.get("message", call_kwargs[1].get("message", ""))
        assert "Could not check" in msg

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run")
    def test_empty_casks_response(self, mock_run, mock_which, mock_rumps):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"casks": []}),
        )
        app = MagicMock(spec=ClaudeMonitorApp)
        app._version_item = MagicMock()
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args
        msg = call_kwargs.kwargs.get("message", call_kwargs[1].get("message", ""))
        assert "Could not check" in msg

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value=None)
    @patch("claude_monitor.app.os.path.isfile")
    def test_brew_found_via_fallback_path(self, mock_isfile, mock_which, mock_rumps):
        """Si shutil.which falla, prueba rutas hardcoded."""
        mock_isfile.side_effect = lambda p: p == "/opt/homebrew/bin/brew"

        with patch("claude_monitor.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"casks": [{"version": "1.3.1"}]}),
            )
            app = MagicMock(spec=ClaudeMonitorApp)
            app._version_item = MagicMock()
            app._is_newer = ClaudeMonitorApp._is_newer

            ClaudeMonitorApp._check_brew_update(app)

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "/opt/homebrew/bin/brew"

    @patch("claude_monitor.app.rumps")
    @patch("claude_monitor.app.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("claude_monitor.app.subprocess.run")
    def test_version_item_restored_after_check(self, mock_run, mock_which, mock_rumps):
        """El titulo del version_item se restaura después del check."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"casks": [{"version": "1.3.1"}]}),
        )
        app = MagicMock(spec=ClaudeMonitorApp)
        version_item = MagicMock()
        app._version_item = version_item
        app._is_newer = ClaudeMonitorApp._is_newer

        ClaudeMonitorApp._check_brew_update(app)

        # Debe restaurar el titulo original
        assert "Version" in version_item.title
