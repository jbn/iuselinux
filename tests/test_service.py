"""Tests for the service module."""

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iuselinux import service
from iuselinux.service import BundleOwnershipError


def test_get_launch_agents_dir():
    """Test that LaunchAgents dir is under user home."""
    result = service.get_launch_agents_dir()
    assert result == Path.home() / "Library" / "LaunchAgents"


def test_get_plist_path():
    """Test plist path construction."""
    result = service.get_plist_path()
    assert result.name == "com.iuselinux.server.plist"
    assert "LaunchAgents" in str(result)


def test_get_log_paths():
    """Test log paths are in Library/Logs."""
    stdout, stderr = service.get_log_paths()
    assert "Library/Logs/iuselinux" in str(stdout)
    assert stdout.name == "iuselinux.log"
    assert stderr.name == "iuselinux.err"


def test_generate_plist_structure():
    """Test plist generation creates valid structure."""
    plist = service.generate_plist(host="127.0.0.1", port=1960)

    assert plist["Label"] == "com.iuselinux.server"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert isinstance(plist["ProgramArguments"], list)
    assert "--port" in plist["ProgramArguments"]
    assert "1960" in plist["ProgramArguments"]
    assert "--host" in plist["ProgramArguments"]
    assert "127.0.0.1" in plist["ProgramArguments"]


def test_generate_plist_custom_port():
    """Test plist uses custom port."""
    plist = service.generate_plist(host="0.0.0.0", port=9999)

    assert "9999" in plist["ProgramArguments"]
    assert "0.0.0.0" in plist["ProgramArguments"]


def test_is_installed_false(tmp_path, monkeypatch):
    """Test is_installed returns False when plist doesn't exist."""
    monkeypatch.setattr(service, "get_plist_path", lambda: tmp_path / "nonexistent.plist")
    assert service.is_installed() is False


def test_is_installed_true(tmp_path, monkeypatch):
    """Test is_installed returns True when plist exists."""
    plist_path = tmp_path / "test.plist"
    plist_path.touch()
    monkeypatch.setattr(service, "get_plist_path", lambda: plist_path)
    assert service.is_installed() is True


@patch("subprocess.run")
def test_is_loaded_true(mock_run):
    """Test is_loaded returns True when launchctl list succeeds."""
    mock_run.return_value = MagicMock(returncode=0)
    assert service.is_loaded() is True
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_is_loaded_false(mock_run):
    """Test is_loaded returns False when launchctl list fails."""
    mock_run.return_value = MagicMock(returncode=1)
    assert service.is_loaded() is False


@patch("subprocess.run")
def test_get_pid_running(mock_run):
    """Test get_pid returns PID when service is running."""
    mock_run.return_value = MagicMock(returncode=0, stdout="12345\t0\tcom.iuselinux.server")
    assert service.get_pid() == 12345


@patch("subprocess.run")
def test_get_pid_not_running(mock_run):
    """Test get_pid returns None when service is not running."""
    mock_run.return_value = MagicMock(returncode=0, stdout="-\t0\tcom.iuselinux.server")
    assert service.get_pid() is None


@patch("subprocess.run")
def test_get_pid_not_loaded(mock_run):
    """Test get_pid returns None when service is not loaded."""
    mock_run.return_value = MagicMock(returncode=1)
    assert service.get_pid() is None


def test_get_status_not_installed(tmp_path, monkeypatch):
    """Test get_status when service is not installed."""
    monkeypatch.setattr(service, "get_plist_path", lambda: tmp_path / "nonexistent.plist")

    status = service.get_status()

    assert status["installed"] is False
    assert status["loaded"] is False
    assert status["running"] is False
    assert status["pid"] is None


def test_format_status_not_installed():
    """Test format_status for not installed service."""
    status = {
        "installed": False,
        "loaded": False,
        "running": False,
        "pid": None,
        "plist_path": None,
    }
    output = service.format_status(status)
    assert "not installed" in output
    assert "iuselinux service install" in output


def test_format_status_running():
    """Test format_status for running service."""
    status = {
        "installed": True,
        "loaded": True,
        "running": True,
        "pid": 12345,
        "plist_path": "/path/to/plist",
        "stdout_log": "/path/to/log",
    }
    output = service.format_status(status)
    assert "running" in output
    assert "12345" in output


def test_uninstall_not_installed(tmp_path, monkeypatch):
    """Test uninstall fails when not installed."""
    monkeypatch.setattr(service, "get_plist_path", lambda: tmp_path / "nonexistent.plist")

    success, message = service.uninstall()

    assert success is False
    assert "not installed" in message


@patch("subprocess.run")
def test_install_already_installed(mock_run, tmp_path, monkeypatch):
    """Test install fails when already installed without --force."""
    plist_path = tmp_path / "test.plist"
    plist_path.touch()
    monkeypatch.setattr(service, "get_plist_path", lambda: plist_path)

    success, message = service.install()

    assert success is False
    assert "already installed" in message


# Tailscale tests

@patch("shutil.which")
def test_is_tailscale_available_true(mock_which):
    """Test is_tailscale_available returns True when tailscale is in PATH."""
    mock_which.return_value = "/usr/local/bin/tailscale"
    assert service.is_tailscale_available() is True


@patch("shutil.which")
def test_is_tailscale_available_false(mock_which):
    """Test is_tailscale_available returns False when tailscale is not found."""
    mock_which.return_value = None
    assert service.is_tailscale_available() is False


@patch("subprocess.run")
@patch("shutil.which")
def test_is_tailscale_connected_true(mock_which, mock_run):
    """Test is_tailscale_connected returns True when connected."""
    mock_which.return_value = "/usr/local/bin/tailscale"
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"BackendState": "Running"}'
    )
    assert service.is_tailscale_connected() is True


@patch("subprocess.run")
@patch("shutil.which")
def test_is_tailscale_connected_false(mock_which, mock_run):
    """Test is_tailscale_connected returns False when not connected."""
    mock_which.return_value = "/usr/local/bin/tailscale"
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"BackendState": "NeedsLogin"}'
    )
    assert service.is_tailscale_connected() is False


@patch("shutil.which")
def test_is_tailscale_connected_not_available(mock_which):
    """Test is_tailscale_connected returns False when tailscale not available."""
    mock_which.return_value = None
    assert service.is_tailscale_connected() is False


@patch("subprocess.Popen")
@patch("subprocess.run")
@patch("shutil.which")
def test_enable_tailscale_serve_success(mock_which, mock_run, mock_popen):
    """Test enabling tailscale serve successfully."""
    mock_which.return_value = "/usr/local/bin/tailscale"
    # subprocess.run is called for is_tailscale_connected
    mock_run.return_value = MagicMock(returncode=0, stdout='{"BackendState": "Running"}')
    # subprocess.Popen is called to start tailscale serve
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # Process is still running
    mock_popen.return_value = mock_proc

    success, message = service.enable_tailscale_serve(port=1960)

    assert success is True
    assert "1960" in message
    mock_popen.assert_called_once()


@patch("shutil.which")
def test_enable_tailscale_serve_not_available(mock_which):
    """Test enabling tailscale serve fails when not available."""
    mock_which.return_value = None

    success, message = service.enable_tailscale_serve()

    assert success is False
    assert "not found" in message.lower()


@patch("subprocess.run")
@patch("shutil.which")
def test_get_tailscale_status(mock_which, mock_run):
    """Test get_tailscale_status returns correct structure."""
    mock_which.return_value = "/usr/local/bin/tailscale"
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"BackendState": "Running"}'
    )

    status = service.get_tailscale_status()

    assert "tailscale_available" in status
    assert "tailscale_connected" in status
    assert "tailscale_serving" in status


# Tailscale PID file tests

def test_get_tailscale_pid_file():
    """Test tailscale PID file path is in ~/.local/state/iuselinux."""
    result = service.get_tailscale_pid_file()
    assert ".local/state/iuselinux" in str(result)
    assert result.name == "tailscale_serve.pid"


def test_write_and_read_tailscale_pid(tmp_path, monkeypatch):
    """Test writing and reading tailscale PID file."""
    pid_file = tmp_path / "tailscale_serve.pid"
    monkeypatch.setattr(service, "get_tailscale_pid_file", lambda: pid_file)

    service._write_tailscale_pid(12345)
    assert pid_file.exists()
    assert service._read_tailscale_pid() == 12345


def test_read_tailscale_pid_nonexistent(tmp_path, monkeypatch):
    """Test reading nonexistent PID file returns None."""
    pid_file = tmp_path / "tailscale_serve.pid"
    monkeypatch.setattr(service, "get_tailscale_pid_file", lambda: pid_file)

    assert service._read_tailscale_pid() is None


def test_remove_tailscale_pid_file(tmp_path, monkeypatch):
    """Test removing tailscale PID file."""
    pid_file = tmp_path / "tailscale_serve.pid"
    pid_file.write_text("12345")
    monkeypatch.setattr(service, "get_tailscale_pid_file", lambda: pid_file)

    service._remove_tailscale_pid_file()
    assert not pid_file.exists()


def test_is_process_running_self():
    """Test _is_process_running returns True for current process."""
    import os
    assert service._is_process_running(os.getpid()) is True


def test_is_process_running_nonexistent():
    """Test _is_process_running returns False for nonexistent PID."""
    # Use a very high PID that's unlikely to exist
    assert service._is_process_running(999999999) is False


@patch("iuselinux.service._is_process_running")
def test_is_tailscale_serving_via_pid_file(mock_is_running, tmp_path, monkeypatch):
    """Test is_tailscale_serving detects serving via PID file."""
    # Setup: no in-process subprocess
    monkeypatch.setattr(service, "_tailscale_serve_proc", None)

    # Setup: PID file exists with running process
    pid_file = tmp_path / "tailscale_serve.pid"
    pid_file.write_text("12345")
    monkeypatch.setattr(service, "get_tailscale_pid_file", lambda: pid_file)
    mock_is_running.return_value = True

    # Should detect as serving via PID file
    with patch("shutil.which", return_value=None):  # No tailscale CLI
        assert service.is_tailscale_serving() is True


@patch("iuselinux.service._is_process_running")
@patch("iuselinux.service._read_tailscale_pid")
@patch("os.kill")
def test_disable_tailscale_serve_cross_process(mock_kill, mock_read_pid, mock_is_running, monkeypatch):
    """Test disable_tailscale_serve works cross-process via PID file."""
    # Setup: no in-process subprocess
    monkeypatch.setattr(service, "_tailscale_serve_proc", None)

    # Setup: PID file contains running process
    mock_read_pid.return_value = 12345
    mock_is_running.side_effect = [True, False]  # First check: running, second: dead

    success, message = service.disable_tailscale_serve()

    assert success is True
    mock_kill.assert_called_with(12345, 15)  # SIGTERM


# Port detection tests

def test_is_port_in_use_available():
    """Test is_port_in_use returns False for available port."""
    # Use a high port that's unlikely to be in use
    result = service.is_port_in_use(host="127.0.0.1", port=59999)
    assert result is False


@patch("socket.socket")
def test_is_port_in_use_busy(mock_socket):
    """Test is_port_in_use returns True when port is busy."""
    mock_sock_instance = MagicMock()
    mock_sock_instance.bind.side_effect = OSError("Address already in use")
    mock_socket.return_value.__enter__.return_value = mock_sock_instance

    result = service.is_port_in_use(host="127.0.0.1", port=1960)
    assert result is True


@patch("subprocess.run")
def test_check_startup_conflicts_service_running(mock_run, tmp_path, monkeypatch):
    """Test check_startup_conflicts detects running service."""
    # Make it look like service is installed and running
    plist_path = tmp_path / "test.plist"
    plist_path.touch()
    monkeypatch.setattr(service, "get_plist_path", lambda: plist_path)

    # Mock launchctl to show service is loaded and running
    mock_run.return_value = MagicMock(returncode=0, stdout="12345\t0\tcom.iuselinux.server")

    can_start, message = service.check_startup_conflicts()

    assert can_start is False
    assert "already running" in message
    assert "12345" in message


@patch("subprocess.run")
def test_check_startup_conflicts_port_in_use(mock_run, tmp_path, monkeypatch):
    """Test check_startup_conflicts detects port in use."""
    # Service is not installed
    monkeypatch.setattr(service, "get_plist_path", lambda: tmp_path / "nonexistent.plist")
    mock_run.return_value = MagicMock(returncode=1)

    # Mock port as in use
    monkeypatch.setattr(service, "is_port_in_use", lambda host, port: True)

    can_start, message = service.check_startup_conflicts()

    assert can_start is False
    assert "already in use" in message


@patch("subprocess.run")
def test_check_startup_conflicts_no_conflict(mock_run, tmp_path, monkeypatch):
    """Test check_startup_conflicts allows start when no conflicts."""
    # Service is not installed
    monkeypatch.setattr(service, "get_plist_path", lambda: tmp_path / "nonexistent.plist")
    mock_run.return_value = MagicMock(returncode=1)

    # Port is available
    monkeypatch.setattr(service, "is_port_in_use", lambda host, port: False)

    can_start, message = service.check_startup_conflicts()

    assert can_start is True
    assert message is None


# Tray LaunchAgent tests


def test_get_tray_plist_path():
    """Test tray plist path construction."""
    result = service.get_tray_plist_path()
    assert result.name == "com.iuselinux.tray.plist"
    assert "LaunchAgents" in str(result)


def test_get_tray_log_paths():
    """Test tray log paths are in Library/Logs."""
    stdout, stderr = service.get_tray_log_paths()
    assert "Library/Logs/iuselinux" in str(stdout)
    assert stdout.name == "tray.log"
    assert stderr.name == "tray.err"


def test_generate_tray_plist_structure():
    """Test tray plist generation creates valid structure."""
    plist = service.generate_tray_plist()

    assert plist["Label"] == "com.iuselinux.tray"
    assert plist["RunAtLoad"] is True
    # KeepAlive is intentionally NOT set - tray should stay quit when user quits it
    assert "KeepAlive" not in plist
    assert isinstance(plist["ProgramArguments"], list)
    # Now uses app bundle launcher instead of direct tray run command
    assert len(plist["ProgramArguments"]) >= 1


def test_is_tray_installed_false(tmp_path, monkeypatch):
    """Test is_tray_installed returns False when plist doesn't exist."""
    monkeypatch.setattr(service, "get_tray_plist_path", lambda: tmp_path / "nonexistent.plist")
    assert service.is_tray_installed() is False


def test_is_tray_installed_true(tmp_path, monkeypatch):
    """Test is_tray_installed returns True when plist exists."""
    plist_path = tmp_path / "test.plist"
    plist_path.touch()
    monkeypatch.setattr(service, "get_tray_plist_path", lambda: plist_path)
    assert service.is_tray_installed() is True


@patch("subprocess.run")
def test_is_tray_loaded_true(mock_run):
    """Test is_tray_loaded returns True when launchctl list succeeds."""
    mock_run.return_value = MagicMock(returncode=0)
    assert service.is_tray_loaded() is True


@patch("subprocess.run")
def test_is_tray_loaded_false(mock_run):
    """Test is_tray_loaded returns False when launchctl list fails."""
    mock_run.return_value = MagicMock(returncode=1)
    assert service.is_tray_loaded() is False


@patch("subprocess.run")
def test_get_tray_pid_running(mock_run):
    """Test get_tray_pid returns PID when tray is running."""
    mock_run.return_value = MagicMock(returncode=0, stdout="54321\t0\tcom.iuselinux.tray")
    assert service.get_tray_pid() == 54321


@patch("subprocess.run")
def test_get_tray_pid_not_running(mock_run):
    """Test get_tray_pid returns None when tray is not running."""
    mock_run.return_value = MagicMock(returncode=0, stdout="-\t0\tcom.iuselinux.tray")
    assert service.get_tray_pid() is None


def test_get_tray_status_not_installed(tmp_path, monkeypatch):
    """Test get_tray_status when tray is not installed."""
    monkeypatch.setattr(service, "get_tray_plist_path", lambda: tmp_path / "nonexistent.plist")

    status = service.get_tray_status()

    assert status["installed"] is False
    assert status["loaded"] is False
    assert status["running"] is False
    assert status["pid"] is None


def test_uninstall_tray_not_installed(tmp_path, monkeypatch):
    """Test uninstall_tray fails when not installed."""
    monkeypatch.setattr(service, "get_tray_plist_path", lambda: tmp_path / "nonexistent.plist")

    success, message = service.uninstall_tray()

    assert success is False
    assert "not installed" in message


@patch("subprocess.run")
def test_install_tray_already_installed(mock_run, tmp_path, monkeypatch):
    """Test install_tray fails when already installed without --force."""
    plist_path = tmp_path / "test.plist"
    plist_path.touch()
    monkeypatch.setattr(service, "get_tray_plist_path", lambda: plist_path)

    success, message = service.install_tray()

    assert success is False
    assert "already installed" in message.lower()


# Bundle ownership verification tests


class TestBundleOwnershipVerification:
    """Tests for bundle ownership verification to prevent overwriting user apps."""

    def test_verify_ownership_nonexistent_bundle(self, tmp_path):
        """Test that verification passes for nonexistent bundles."""
        app_path = tmp_path / "NonExistent.app"
        assert service.verify_bundle_ownership(app_path, "com.example.test") is True

    def test_verify_ownership_our_bundle(self, tmp_path):
        """Test that verification passes for our own bundle."""
        app_path = tmp_path / "Test.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.iuselinux.tray",
            "CFBundleName": "Test",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        assert service.verify_bundle_ownership(app_path, "com.iuselinux.tray") is True

    def test_verify_ownership_different_bundle_raises_error(self, tmp_path):
        """Test that verification fails for a bundle with different identifier."""
        app_path = tmp_path / "OtherApp.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.other.app",
            "CFBundleName": "Other App",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.verify_bundle_ownership(app_path, "com.iuselinux.tray")

        assert "com.other.app" in str(exc_info.value)
        assert "com.iuselinux.tray" in str(exc_info.value)

    def test_verify_ownership_missing_info_plist_raises_error(self, tmp_path):
        """Test that verification fails for bundle without Info.plist."""
        app_path = tmp_path / "MalformedApp.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)
        # No Info.plist created

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.verify_bundle_ownership(app_path, "com.iuselinux.tray")

        assert "no Info.plist" in str(exc_info.value)

    def test_verify_ownership_invalid_plist_raises_error(self, tmp_path):
        """Test that verification fails for bundle with invalid plist."""
        app_path = tmp_path / "CorruptApp.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        # Write invalid plist data
        with open(contents_path / "Info.plist", "w") as f:
            f.write("this is not a valid plist")

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.verify_bundle_ownership(app_path, "com.iuselinux.tray")

        assert "invalid Info.plist" in str(exc_info.value)

    def test_verify_ownership_empty_identifier_raises_error(self, tmp_path):
        """Test that verification fails for bundle with empty identifier."""
        app_path = tmp_path / "NoIdApp.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleName": "No Identifier App",
            # CFBundleIdentifier is missing
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.verify_bundle_ownership(app_path, "com.iuselinux.tray")

        assert "com.iuselinux.tray" in str(exc_info.value)

    def test_create_tray_app_bundle_refuses_foreign_bundle(self, tmp_path, monkeypatch):
        """Test that create_tray_app_bundle refuses to overwrite foreign apps."""
        # Create a foreign app at the expected location
        app_path = tmp_path / "iUseLinux.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.someuser.myapp",
            "CFBundleName": "User's App",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        # Mock the path functions
        monkeypatch.setattr(service, "get_tray_app_bundle_path", lambda: app_path)
        monkeypatch.setattr(service, "get_user_applications_dir", lambda: tmp_path)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.create_tray_app_bundle()

        assert "com.someuser.myapp" in str(exc_info.value)

    def test_remove_tray_app_bundle_refuses_foreign_bundle(self, tmp_path, monkeypatch):
        """Test that remove_tray_app_bundle refuses to delete foreign apps."""
        # Create a foreign app at the expected location
        app_path = tmp_path / "iUseLinux.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.someuser.myapp",
            "CFBundleName": "User's App",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        # Mock the path function
        monkeypatch.setattr(service, "get_tray_app_bundle_path", lambda: app_path)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.remove_tray_app_bundle()

        assert "com.someuser.myapp" in str(exc_info.value)
        # Verify the app was NOT deleted
        assert app_path.exists()

    def test_create_app_bundle_refuses_foreign_bundle(self, tmp_path, monkeypatch):
        """Test that create_app_bundle refuses to overwrite foreign apps."""
        # Create a foreign app at the expected location
        app_path = tmp_path / "iUseLinux Service.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.someuser.myservice",
            "CFBundleName": "User's Service",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        # Mock the path function
        monkeypatch.setattr(service, "get_app_bundle_path", lambda: app_path)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.create_app_bundle()

        assert "com.someuser.myservice" in str(exc_info.value)

    def test_remove_app_bundle_refuses_foreign_bundle(self, tmp_path, monkeypatch):
        """Test that remove_app_bundle refuses to delete foreign apps."""
        # Create a foreign app at the expected location
        app_path = tmp_path / "iUseLinux Service.app"
        contents_path = app_path / "Contents"
        contents_path.mkdir(parents=True)

        info_plist = {
            "CFBundleIdentifier": "com.someuser.myservice",
            "CFBundleName": "User's Service",
        }
        with open(contents_path / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        # Mock the path function
        monkeypatch.setattr(service, "get_app_bundle_path", lambda: app_path)

        with pytest.raises(BundleOwnershipError) as exc_info:
            service.remove_app_bundle()

        assert "com.someuser.myservice" in str(exc_info.value)
        # Verify the app was NOT deleted
        assert app_path.exists()
