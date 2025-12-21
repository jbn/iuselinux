# iUseLinux Install/Uninstall Audit Report

**Date:** 2025-12-20
**Audited Components:** Makefile, service.py, config.py, api.py, updater.py, tray integration, Tailscale integration, test coverage

---

## Executive Summary

This audit examines all install, uninstall, and update functionality to ensure users can always cleanly remove or update the application. **42 issues were identified**, ranging from critical bugs that could leave the system in an inconsistent state to minor UX improvements.

**Progress:** 17 issues fixed/mitigated (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 20, 21, 31, 32, 33, 42), 25 remaining.

---

## Issues by Severity

### CRITICAL (Must Fix - Could Leave System in Broken State)

| # | Component | Issue | Impact |
|---|-----------|-------|--------|
| ~~1~~ | ~~**Makefile**~~ | ~~Missing LaunchAgent plist cleanup if `uvx uninstall` fails~~ | ~~FIXED in f03b2fe~~ |
| ~~2~~ | ~~**Auto-Update**~~ | ~~No rollback capability after failed update~~ | ~~N/A - Auto-update disabled, manual updates only~~ |
| ~~3~~ | ~~**Auto-Update**~~ | ~~`launchctl kickstart` return code not checked~~ | ~~N/A - Auto-update disabled, manual updates only~~ |
| ~~4~~ | ~~**Auto-Update**~~ | ~~`os.execv` restart may use wrong Python after update~~ | ~~N/A - Auto-update disabled, manual updates only~~ |
| ~~5~~ | ~~**Service Install**~~ | ~~launchctl unload failure in `install()` is silently ignored~~ | ~~FIXED: now checks return code and fails with clear message~~ |
| ~~6~~ | ~~**Service Uninstall**~~ | ~~launchctl unload failure blocks all cleanup~~ | ~~FIXED: best-effort cleanup with warnings~~ |
| ~~7~~ | ~~**Config**~~ | ~~No atomic write - crash during save corrupts config~~ | ~~FIXED: atomic write with tempfile+os.replace~~ |
| ~~8~~ | ~~**Config**~~ | ~~No file locking - concurrent writes silently lose data~~ | ~~FIXED: fcntl.LOCK_EX on read-modify-write ops~~ |
| 9 | **API Security** | No authorization on `/service/install`, `/service/uninstall` | Malicious local process can control service |
| ~~10~~ | ~~**API Security**~~ | ~~Race conditions in install/uninstall operations~~ | ~~FIXED: fcntl.flock() serializes operations~~ |
| ~~11~~ | ~~**API Security**~~ | ~~Race conditions in Tailscale enable/disable~~ | ~~FIXED: PID file provides atomic state~~ |
| ~~12~~ | ~~**Tailscale**~~ | ~~Cross-process control doesn't work~~ | ~~FIXED: PID file at ~/.local/state/iuselinux/tailscale_serve.pid~~ |
| ~~13~~ | ~~**Tailscale**~~ | ~~Non-graceful restart may leave orphan tailscale serve~~ | ~~FIXED: Orphan cleanup on startup via PID file~~ |

---

### HIGH (Should Fix - Causes User Confusion or Data Issues)

| # | Component | Issue | Impact |
|---|-----------|-------|--------|
| 14 | **Makefile** | Service app bundle not explicitly removed | `~/Library/Application Support/iuselinux/iUseLinux Service.app/` may persist |
| 15 | **Service Install** | No wait after launchctl unload before new load | Race condition during reinstall |
| 16 | **Service Install** | App bundle creation failure not handled | Partial installation state |
| 17 | **Service Uninstall** | Logs not cleaned up | `~/Library/Logs/iuselinux/` accumulates indefinitely |
| 18 | **Tray Uninstall** | Tray logs not cleaned up | `tray.log`, `tray.err` persist |
| 19 | **Tray Install** | `create_tray_app_bundle()` failure not caught | Exception crashes install |
| ~~20~~ | ~~**Auto-Update**~~ | ~~Updates interrupt user without warning~~ | ~~N/A - Auto-update disabled, manual updates only~~ |
| ~~21~~ | ~~**Auto-Update**~~ | ~~Background task exits after first successful update~~ | ~~N/A - Auto-update disabled, banner checks continue~~ |
| 22 | **Config** | Silent corruption recovery - no warning to user | User doesn't know settings were reset |
| 23 | **Config** | Inconsistent uninstall behavior (3 different methods) | User confusion about what's removed |
| 24 | **API Security** | No rate limiting on service endpoints | DoS via repeated install/uninstall |
| 25 | **API Security** | Error messages leak system details | Information disclosure |
| 26 | **API Security** | Non-atomic side effects with no rollback | Failed installs leave orphaned files |
| 27 | **Test Coverage** | 0% coverage of actual `install()`/`uninstall()` flows | Regressions not detected |

---

### MEDIUM (Should Address - UX or Minor Reliability Issues)

| # | Component | Issue | Impact |
|---|-----------|-------|--------|
| 28 | **Makefile** | `-` prefix suppresses all errors from `uvx uninstall` | Silent failures with no user feedback |
| 29 | **Makefile** | Missing temp cache cleanup (`$TMPDIR/iuselinux_*`) | Disk space waste |
| 30 | **Service Uninstall** | Returns failure when not installed (not idempotent) | Cleanup scripts more complex |
| ~~31~~ | ~~**Auto-Update**~~ | ~~Error handling sleeps hardcoded 1 hour on ANY error~~ | ~~N/A - Auto-update disabled~~ |
| ~~32~~ | ~~**Auto-Update**~~ | ~~No user notification before auto-update~~ | ~~N/A - Auto-update disabled, banner shown instead~~ |
| ~~33~~ | ~~**Auto-Update**~~ | ~~Restart delay inconsistent (2s vs 5s)~~ | ~~N/A - Auto-update disabled~~ |
| 34 | **Config** | API token in config file has default 644 permissions | Other users can read token |
| 35 | **Config** | No `--purge` option to remove all data | Manual cleanup required |
| 36 | **Tailscale** | No port conflict detection | Confusing errors |
| 37 | **Tailscale** | No subprocess health monitoring | Config says enabled but not running (partially mitigated by PID file check) |
| 38 | **CLI** | `tray run` has no error handling | Stack trace instead of helpful message |
| 39 | **CLI** | No progress indication for long operations | Appears to hang |
| 40 | **API Security** | subprocess.run() without timeouts | DoS risk |
| 41 | **API Security** | Insufficient host/port validation | Potential for invalid input |
| ~~42~~ | ~~**Test Coverage**~~ | ~~0% coverage of auto-updater~~ | ~~N/A - Auto-update disabled~~ |

---

### LOW (Nice to Have - Polish)

| # | Component | Issue | Impact |
|---|-----------|-------|--------|
| 43 | **CLI** | Inconsistent color coding in tray commands | Minor UX inconsistency |
| 44 | **CLI** | Main command help doesn't explain default behavior | Minor documentation gap |
| 45 | **Config** | Orphaned keys not cleaned up when defaults change | File clutter |

---

## Detailed Findings by Component

### 1. Makefile (`remove-install` / `reset-install`)

**FIXED in commit f03b2fe**

The `remove-install` target now explicitly unloads LaunchAgents and removes plist files as a fallback:
```makefile
remove-install:
	-launchctl unload ~/Library/LaunchAgents/com.iuselinux.server.plist 2>/dev/null
	-launchctl unload ~/Library/LaunchAgents/com.iuselinux.tray.plist 2>/dev/null
	-uvx iuselinux service uninstall
	rm -f ~/Library/LaunchAgents/com.iuselinux.server.plist
	rm -f ~/Library/LaunchAgents/com.iuselinux.tray.plist
	rm -rf ~/.local/share/uv/tools/iuselinux
	rm -f ~/.local/bin/iuselinux
	rm -rf ~/Library/Application\ Support/iuselinux/
	rm -rf ~/Library/Logs/iuselinux/
	rm -rf ~/Applications/iUseLinux.app/
```

**Remaining minor issue:**
- Temp caches at `$TMPDIR/iuselinux_*` are not cleaned (low priority)

---

### 2. Service LaunchAgent Installation (`service.py`)

**FIXED** - Issues 5 & 6 resolved on 2025-12-20:

1. ~~**launchctl unload not checked in install()**~~: Now checks return code and fails with clear error message if existing service can't be unloaded
2. ~~**launchctl unload blocks uninstall cleanup**~~: Now uses best-effort cleanup - continues removing components even if launchctl unload fails
3. ~~**plist_path.unlink() OSError propagates**~~: Now caught and added to warnings

**Remaining Issues:**
- Line 441: `create_app_bundle()` can fail but exception is not caught, leaving partial state (issue #16)
- No log cleanup - files accumulate indefinitely (issue #17)

---

### 3. Tray App Installation

**Issues:**
- `install_tray()` line 934: `create_tray_app_bundle()` not wrapped in try/except
- `uninstall_tray()`: Does not clean up `~/Library/Logs/iuselinux/tray.log` and `tray.err`
- No error recovery if app bundle creation fails midway

**Good:**
- `KeepAlive` correctly NOT set for tray (user can quit permanently)
- Proper integration with service install/uninstall
- `~/Applications` directory created if missing

---

### 4. Tailscale Integration

**FIXED** - Issues 11, 12 & 13 resolved:

The implementation uses foreground mode (`tailscale serve <port>` without `--bg`), which ties the serve lifecycle to the iuselinux process. This is the right approach for ensuring no ports stay open accidentally.

**Implementation Details:**

1. ~~**Cross-process control (Issue #12)**~~: Now uses PID file at `~/.local/state/iuselinux/tailscale_serve.pid`
   - `enable_tailscale_serve()` writes subprocess PID to file
   - `disable_tailscale_serve()` reads PID file and sends SIGTERM for cross-process control
   - `is_tailscale_serving()` checks PID file for cross-process detection

2. ~~**Non-graceful restart orphans (Issue #13)**~~: Now has orphan cleanup on startup
   - `_kill_orphan_tailscale_serve()` called before starting new serve
   - Reads stale PID file, checks if process running, terminates if so
   - Cleans up PID file after termination

3. ~~**Race conditions (Issue #11)**~~: PID file provides atomic state
   - Single source of truth for "is tailscale serve running"
   - `atexit` handler registered for graceful cleanup
   - `start_new_session=True` creates process group for cleaner termination

**Remaining Minor Issues:**
- No port conflict detection before starting serve (issue #36)
- Config says "enabled" but process may have died (issue #37 - partially addressed by PID file check)

---

### 5. Auto-Update Mechanism (`updater.py`)

**Status:** ✅ **MITIGATED** - Auto-update disabled on 2025-12-20

Auto-update functionality has been disabled. Updates are now handled via:
- Banner notification shown in the UI when updates are available
- Major version updates: Red banner, cannot be dismissed
- Minor/patch updates: Beige banner, dismissable for 48 hours
- User manually runs the displayed command to update

The following issues are no longer applicable:
- ~~No rollback if update fails~~ - User controls when to update
- ~~launchctl kickstart return code not checked~~ - No automatic restart
- ~~os.execv restart uses stale sys.executable~~ - No automatic restart
- ~~Updates happen without notification~~ - Banner shown instead
- ~~Hardcoded 1-hour retry~~ - No background update task
- ~~Background task exits after first update~~ - No background update task

---

### 6. Configuration Management (`config.py`)

**FIXED** - Issues 7 & 8 resolved:

1. ~~**No atomic write**~~: Now uses `tempfile.mkstemp()` + `os.replace()` for crash-safe writes
2. ~~**No file locking**~~: Now uses `fcntl.LOCK_EX` with a separate `.config.lock` file for all read-modify-write operations
3. **Silent corruption**: Corrupted JSON still returns defaults with no warning (unchanged - low priority)

**Implementation:**
- `_save_config()` writes to temp file, flushes, fsyncs, then atomically renames
- `_config_lock()` context manager provides exclusive locking
- `set_config_value()`, `update_config()`, `reset_config()` all use the lock

---

### 7. CLI Commands (`api.py`)

**Issues:**
- `tray run` has no error handling - exceptions show stack trace
- `service uninstall` not idempotent - fails if not installed
- No progress indication for long operations

**Good:**
- Proper exit codes (0/1)
- Good error messages with color
- Excellent Tailscale pre-validation

---

### 8. REST API Endpoints

**Security Issues:**
- No authorization on service management endpoints
- No rate limiting
- Race conditions on concurrent operations
- Error messages leak system details
- subprocess.run() without timeouts (DoS risk)

**Concurrency Issues:**
- Install/uninstall can race with unpredictable results
- No locking mechanism

---

### 9. Test Coverage

**Current State:**
- ~25% coverage for install/uninstall functionality
- Basic utility functions tested
- **0% coverage of actual install/uninstall flows**
- **0% coverage of auto-updater**
- **0% coverage of app bundle creation**

**Critical Missing Tests:**
- `install()` success path
- `uninstall()` success path
- `install(force=True)` reinstallation
- App bundle creation/removal
- Launchctl integration
- Auto-update lifecycle

---

## Files Installed/Modified

| Path | Created By | Removed By | Notes |
|------|-----------|------------|-------|
| `~/.local/bin/iuselinux` | `uv tool install` | Makefile | CLI symlink |
| `~/.local/share/uv/tools/iuselinux/` | `uv tool install` | Makefile | Python package |
| `~/Library/LaunchAgents/com.iuselinux.server.plist` | `service install` | `service uninstall` | LaunchAgent config |
| `~/Library/LaunchAgents/com.iuselinux.tray.plist` | `service install` | `service uninstall` | Tray LaunchAgent |
| `~/Library/Application Support/iuselinux/iUseLinux Service.app/` | `service install` | `service uninstall` | Service app bundle |
| `~/Library/Application Support/iuselinux/config.json` | First config write | NOT removed | User preferences |
| `~/Applications/iUseLinux.app/` | `service install` | `service uninstall` | Tray app bundle |
| `~/Library/Logs/iuselinux/` | First service run | NOT removed | Service logs |
| `~/.local/state/iuselinux/tailscale_serve.pid` | Tailscale enable | Tailscale disable / service exit | Tailscale subprocess PID |
| `$TMPDIR/iuselinux_cache/` | Runtime | NOT removed | Video thumbnails |
| `$TMPDIR/iuselinux_uploads/` | Runtime | NOT removed | Upload temp files |

---

## Recommended Priority Order

### Phase 1: Critical Stability
1. ~~Fix Makefile to always remove LaunchAgent plists~~ ✅ DONE (f03b2fe)
2. ~~Add atomic config writes with file locking~~ ✅ DONE (issues 7 & 8 fixed)
3. ~~Fix Tailscale cross-process control~~ ✅ DONE (issues 11, 12 & 13 fixed via PID file)
4. ~~Fix launchctl error handling in install/uninstall~~ ✅ DONE (issues 5 & 6 fixed)
5. ~~Add user confirmation before auto-update~~ ✅ N/A (auto-update disabled, banner shown instead)

### Phase 2: Reliability
6. ~~Add rollback capability for auto-updates~~ ✅ N/A (auto-update disabled)
7. Clean up logs on uninstall (or add flag)
8. Add rate limiting to API endpoints

### Phase 3: Testing & Polish
9. Add tests for install/uninstall flows
10. ~~Add tests for auto-updater~~ ✅ N/A (auto-update disabled)
11. Improve error messages
12. Add progress indicators

---

## Verification Checklist

After fixes are applied, verify:

- [ ] `make remove-install` leaves no files behind
- [ ] Service can be reinstalled cleanly after uninstall
- [ ] Failed update doesn't break running service
- [ ] Concurrent API calls don't corrupt state
- [ ] Config survives reinstall but not purge
- [x] Tailscale serve stops when service stops (FIXED: atexit handler + PID file cleanup)
- [x] CLI can disable Tailscale started by service (FIXED: cross-process control via PID file)
- [x] Service restart doesn't leave orphan Tailscale processes (FIXED: orphan cleanup on startup)
- [ ] User is warned before auto-update restart
