# Security Audit: OS-Affecting Operations

This document audits all operations in the iuselinux codebase that could potentially affect the user's operating system, other applications, or system stability.

---

## Executive Summary

| Category | Risk Level | Could Break OS/Apps? | Summary |
|----------|------------|---------------------|---------|
| ~~AppleScript Sender~~ | ~~CRITICAL~~ | ~~Yes (via injection)~~ | ✅ **FIXED** - Control character escaping added |
| ~~File System Operations~~ | ~~HIGH~~ | ~~Yes (disk exhaustion)~~ | ✅ **FIXED** - Path traversal and disk space checks added |
| ~~Auto-Update System~~ | ~~HIGH~~ | ~~Possible (supply chain)~~ | ✅ **MITIGATED** - Auto-update disabled, banner notifications only |
| ~~App Bundle Creation~~ | ~~MEDIUM-HIGH~~ | ~~Yes (overwrites apps)~~ | ✅ **FIXED** - Bundle ownership verified before overwrite/delete |
| ~~LaunchAgent Operations~~ | ~~MEDIUM~~ | ~~No~~ | ✅ **FIXED** - Best-effort cleanup with warnings |
| ~~Network Operations~~ | ~~MEDIUM~~ | ~~No (resource exhaustion only)~~ | ✅ **FIXED** - WebSocket connection limit; Tailscale cleanup |
| ~~Process Management~~ | ~~LOW~~ | ~~No~~ | ✅ **FIXED/WONTFIX** - Caffeinate fixed; FFmpeg acceptable risk |

---

## ~~CRITICAL FINDINGS~~ (ALL FIXED)

### ~~1. AppleScript Command Injection (sender.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issue:** The `_escape_applescript_string()` function only escaped backslashes and double quotes, but did NOT escape newline or other control characters, allowing command injection.

**Fix Applied:** Added escaping for `\n`, `\r`, and `\t` control characters in `src/iuselinux/sender.py:29-34`.

**Tests Added:** `tests/test_sender.py` - `TestEscapeApplescriptString` class with 12 tests including injection prevention tests.

---

### ~~2. Path Traversal in Static File Serving (api.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issue:** No path traversal protection when serving static files.

**Fix Applied:** Added `.resolve()` and `is_relative_to()` check in `src/iuselinux/api.py:258-263`.

**Tests Added:** `tests/test_api.py` - `TestStaticFileServing` class with 7 tests for various path traversal attempts.

---

## HIGH SEVERITY FINDINGS

### ~~3. Supply Chain Attack Surface (updater.py)~~ ✅ MITIGATED

**Status:** ✅ **MITIGATED** on 2025-12-20

**Original Issue:** Auto-update enabled by default with silent updates that could be exploited via DNS spoofing or compromised PyPI.

**Mitigation Applied:**
- Disabled auto-update functionality entirely
- Removed background update task that performed automatic installs
- Updates now shown via a notification banner instead
- Major version updates: Red banner, cannot be dismissed
- Minor/patch updates: Beige banner, dismissable for 48 hours
- Banner displays the command to run for manual update

**Files Modified:**
- `src/iuselinux/config.py` - Removed `auto_update_enabled` setting
- `src/iuselinux/api.py` - Removed background update task, added `/version/dismiss-banner` endpoint
- `src/iuselinux/updater.py` - Added `get_version_change_type()` for semver detection
- `src/iuselinux/static/index.html` - Added update banner, removed Install Update button
- `src/iuselinux/static/styles.css` - Added banner styles
- `src/iuselinux/static/app.js` - Added banner logic with dismissal

---

### ~~4. Disk Space Exhaustion Risk (api.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-21

**Original Issues:**
- Files up to 100MB accepted with no disk space check
- Uploads stored in `/tmp/iuselinux_uploads` (shared system partition)
- Thumbnail cache has no size limit (`/tmp/iuselinux_cache`)

**Fix Applied:**
- Added `_check_disk_space()` helper function in `src/iuselinux/api.py:816-832`
- Requires 1GB free space buffer (`MIN_FREE_DISK_SPACE`) plus the file size
- Upload endpoint now returns HTTP 507 (Insufficient Storage) if disk is low
- Thumbnail cache skips writing if disk space is low (graceful degradation)

**Locations:**
- Upload check: `src/iuselinux/api.py:913-918`
- Cache check: `src/iuselinux/api.py:1237-1239`

**Impact:** System can no longer be DoS'd via disk exhaustion through this application.

---

### 4. Supply Chain Attack Surface (updater.py)

**Risk Level: HIGH**

**Location:** `src/iuselinux/updater.py:31-134`

**Issues:**
- No package integrity verification (checksums/signatures)
- Authentication optional by default for `/version/update` endpoint
- Silent auto-updates enabled by default
- No rollback mechanism

**Attack Scenarios:**
- DNS spoofing to redirect PyPI requests
- Compromised PyPI package
- Unauthenticated update trigger by local attacker

**Recommendations:**
- Make authentication mandatory for update endpoints
- Disable auto-update by default (opt-in)
- Implement package hash/signature verification
- Add user confirmation before restart

---

### ~~5. App Bundle Overwrite Risk (service.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issue:** `create_tray_app_bundle()` and `remove_tray_app_bundle()` would silently overwrite/delete any existing `~/Applications/iUseLinux.app` without verifying ownership.

**Fix Applied:**
- Added `verify_bundle_ownership()` function in `src/iuselinux/service.py:164-200`
- Added `BundleOwnershipError` exception class
- Both `create_tray_app_bundle()` and `remove_tray_app_bundle()` now verify the CFBundleIdentifier before modifying
- Also fixed `create_app_bundle()` and `remove_app_bundle()` for the service bundle (issue 11)

**Tests Added:** `tests/test_service.py` - `TestBundleOwnershipVerification` class with 10 tests covering:
- Verification passes for nonexistent bundles
- Verification passes for our own bundles
- Verification rejects foreign bundles with different identifiers
- Verification rejects bundles without Info.plist
- Verification rejects bundles with invalid/corrupt plists
- Integration tests for create/remove functions refusing to touch foreign bundles

---

## MEDIUM SEVERITY FINDINGS

### ~~6. LaunchAgent Error Handling (service.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issue:** If `launchctl unload` fails during uninstall, the function returns early without cleaning up plist file or app bundles, leaving system in inconsistent state.

**Fix Applied:**
- `uninstall()` now uses best-effort cleanup - continues removing components even if some steps fail
- Collects warnings instead of returning early on `launchctl unload` failure
- Also handles `plist_path.unlink()` OSError gracefully
- Returns success with warnings appended to message

**Also Fixed (issue #5):**
- `install()` now checks `launchctl unload` return code and fails early with clear error message if existing service can't be unloaded

---

### ~~7. WebSocket DoS Vulnerability (api.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-21

**Location:** `src/iuselinux/api.py:1819-1927`

**Original Issues:**
- No limit on concurrent WebSocket connections
- No rate limiting on WebSocket endpoint
- Infinite polling loop with database queries

**Fix Applied:**
- Added `MAX_WEBSOCKET_CONNECTIONS = 10` limit
- Added `_active_websockets` set to track connections
- New connections rejected with code 1008 when limit reached
- Connections properly tracked on accept and removed in `finally` block
- Logging includes connection count for monitoring

**Impact:** WebSocket DoS attack no longer possible - resource consumption is bounded.

---

### ~~8. Tailscale Cleanup Issues (service.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issues:**
- No cleanup on SIGKILL or uncaught exceptions
- If process crashes, Tailscale serve may continue running
- stderr buffer could cause deadlock

**Fix Applied:**
- Added `atexit.register(_cleanup_tailscale_serve_atexit)` for graceful cleanup
- Added PID file at `~/.local/state/iuselinux/tailscale_serve.pid` for cross-process visibility
- Added `_kill_orphan_tailscale_serve()` called on startup to clean up orphans from crashes/SIGKILL
- Uses `start_new_session=True` for cleaner process group termination
- stderr is drained immediately (0.5s delay) before continuing, avoiding deadlock

**Impact:** Tailscale serve lifecycle now properly tied to iuselinux process with robust orphan cleanup.

---

## LOW SEVERITY FINDINGS

### 9. Orphan Process Risk (api.py) - WONTFIX

**Risk Level: LOW**

**Status:** WONTFIX - Acceptable risk

**Location:** `src/iuselinux/api.py:1257-1300`

**Issue:** FFmpeg streaming generator may leave orphan processes if client disconnects mid-stream.

**Why not fixing:**
- Existing `finally` block already handles normal cleanup
- FFmpeg processes are short-lived (finish when transcoding completes)
- No OS or system impact - just temporary resource consumption
- Rare in practice - most users complete or close streams normally
- Adding process groups adds complexity for minimal benefit

---

### ~~10. Caffeinate Persistence (api.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20

**Original Issue:** If Python process crashes (SIGKILL, segfault), caffeinate continues running.

**Fix Applied:**
- Added `_cleanup_caffeinate_atexit()` handler in `src/iuselinux/api.py:70-72`
- Added `_caffeinate_atexit_registered` flag to avoid multiple registrations
- `atexit.register()` called when caffeinate is started (lines 108-111)

**Impact:** Caffeinate now cleaned up on graceful process exit. Note: atexit handlers don't run on SIGKILL, but do run on normal exit, SIGTERM, and uncaught exceptions.

---

### ~~11. Unsafe Bundle Deletion (service.py)~~ ✅ FIXED

**Status:** ✅ **FIXED** on 2025-12-20 (as part of issue 5 fix)

**Original Issue:** `remove_tray_app_bundle()` and `remove_app_bundle()` didn't verify bundle ownership before deletion.

**Fix Applied:** Both functions now call `verify_bundle_ownership()` before `shutil.rmtree()`. See issue 5 for details.

---

## SAFE OPERATIONS

The following were audited and found to be safe:

| Operation | Location | Status |
|-----------|----------|--------|
| LaunchAgent file locations | service.py:36-43 | SAFE - Uses ~/Library/LaunchAgents only |
| Scoped launchctl commands | service.py | SAFE - All use specific service labels |
| FFmpeg/FFprobe commands | api.py:1121-1300 | SAFE - List arguments, no shell=True |
| Config file writes | config.py | SAFE - User's config directory only |
| Port binding | api.py:1981 | SAFE - Conflict detection, localhost default |
| Permission changes (chmod) | service.py:129-225 | SAFE - Standard 755 for executables |

---

## Summary: Could This Break Other Applications or the OS?

### Direct OS Impact: LOW
- Operations are scoped to user directories
- LaunchAgent commands target specific services
- No system-wide file modifications

### Indirect Risks: MEDIUM-HIGH
1. ~~**AppleScript injection** could execute arbitrary code~~ ✅ FIXED
2. ~~**Path traversal** could expose sensitive files~~ ✅ FIXED
3. **Disk exhaustion** in `/tmp` affects all applications
4. **Supply chain attack** via update could compromise system

### Specific Guarantees:
- No modifications to `/System` or `/Library` (system paths)
- No operations requiring root/admin privileges
- All launchctl operations scoped to user's UID
- Process termination only affects tracked child processes

---

## Recommendations Priority

### Immediate (Pre-Production):
1. ~~Fix AppleScript newline escaping (CRITICAL)~~ ✅ FIXED
2. ~~Add path traversal protection to static files (CRITICAL)~~ ✅ FIXED
3. ~~Disable auto-update, use banner notifications (HIGH)~~ ✅ MITIGATED
4. Add disk space checks for uploads (HIGH)

### Short-Term:
5. ~~Verify bundle ownership before overwrite/delete~~ ✅ FIXED
6. Implement WebSocket connection limits
7. ~~Add atexit handlers for process cleanup~~ ✅ FIXED (Tailscale)
8. Improve uninstall error handling

### Medium-Term:
9. Implement package signature verification
10. Add cache size limits
11. Use process groups for FFmpeg
12. Add comprehensive audit logging

---

*Audit completed: 2025-12-20*
*Audited by: Claude Code with 7 parallel sub-agents*

*Issues 1 & 2 fixed: 2025-12-20*
*Fixed by: Claude Code - Added control character escaping and path traversal protection with unit tests*

*Issue 3 mitigated: 2025-12-20*
*Mitigated by: Claude Code - Disabled auto-update, added banner notification system with semver-based styling*

*Issues 5 & 11 fixed: 2025-12-20*
*Fixed by: Claude Code - Added bundle ownership verification with CFBundleIdentifier check before overwrite/delete*

*Issue 8 fixed: 2025-12-20*
*Fixed by: Claude Code - Added PID file, atexit handler, and orphan cleanup for Tailscale serve subprocess*
