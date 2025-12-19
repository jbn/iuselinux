# iuselinux

A web interface for reading and sending iMessages on macOS.

## Quick Start

Run directly with uvx (no installation required):

```bash
uvx iuselinux@latest
```

Then open http://127.0.0.1:1960 in your browser.

Options:
```bash
uvx iuselinux@latest --host 0.0.0.0 --port 8000
uvx iuselinux@latest --api-token SECRET
```

## Installation

For persistent installation (adds `iuselinux` to your PATH):

```bash
uv tool install iuselinux
```

For development:

```bash
uv pip install -e .
uv sync --group dev
```

## Initial Setup

**Important:** iUseLinux needs **Full Disk Access** permission to read the iMessage database.

**If running from terminal** (e.g., `uvx iuselinux`):
1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
2. Click the **+** button and add your terminal app (Terminal, iTerm2, VS Code, etc.)
3. **Restart your terminal** for the permission to take effect

**If running as a service** (e.g., `uvx iuselinux service install`):
See [Full Disk Access for Service Mode](#full-disk-access-for-service-mode) below.

Without this permission, iUseLinux will show an error page explaining how to fix it.

## Run as Service (Recommended)

Install as a macOS LaunchAgent that starts on login and auto-restarts:

```bash
# Basic install (localhost only)
uv tool install iuselinux && uvx iuselinux service install

# With custom port
uvx iuselinux service install --port 8000

# With Tailscale remote access
uvx iuselinux service install --tailscale

# Skip the menu bar tray icon
uvx iuselinux service install --no-tray
```

Manage the service:

```bash
# Check status
uvx iuselinux service status

# Uninstall
uvx iuselinux service uninstall
```

### Full Disk Access for Service Mode

When running as a service, you need to grant Full Disk Access to the iUseLinux launcher app (not your terminal):

1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
2. Click the **+** button
3. Press **Cmd+Shift+G** and enter: `~/Library/Application Support/iuselinux/`
4. Select **iUseLinux Service.app** and click **Open**
5. Restart the service: `uvx iuselinux@latest service uninstall && uvx iuselinux@latest service install`

The service install creates this app bundle automatically. It's a lightweight wrapper that allows macOS to grant Full Disk Access to the background service.

### Menu Bar Tray

By default, a menu bar icon is installed with the service. Manage it separately:

```bash
uvx iuselinux tray status
uvx iuselinux tray start
uvx iuselinux tray stop
```

## Features

- View all conversations and messages
- Send messages and attachments via the web UI
- Real-time updates via WebSocket
- Search messages
- Attachment support (images, videos with HEIC→WebP and MOV→MP4 conversion)
- Contact name and photo resolution
- Menu bar tray icon for quick access
- Light/dark/auto theme
- Browser notifications with custom sounds
- Custom CSS theming
- API token authentication (optional)
- Prevents Mac from sleeping while running (configurable)
- Auto-updates

## Local Network Access

Bind to all interfaces for LAN access:

```bash
uvx iuselinux --host 0.0.0.0
```

Access from any device on your network at `http://your-mac-ip:1960`

Find your Mac's IP:
```bash
ipconfig getifaddr en0
```

**Warning**: This exposes iuselinux to everyone on your local network. Use `--api-token SECRET` for basic protection.

## Remote Access via SSH Tunnel

The API binds to `127.0.0.1` by default for security. To access it remotely, use an SSH tunnel.

### From your remote machine

```bash
ssh -L 1960:localhost:1960 user@your-mac-ip
```

This forwards your remote machine's `localhost:1960` to the Mac's `localhost:1960`.

Now access the API at `http://localhost:1960` from your remote machine.

### Persistent tunnel with autossh

Install autossh for auto-reconnecting tunnels:

```bash
# On Linux
sudo apt install autossh

# On Mac (remote machine)
brew install autossh
```

Run with auto-reconnect:

```bash
autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" \
    -L 1960:localhost:1960 user@your-mac-ip
```

### SSH config shortcut

Add to `~/.ssh/config` on your remote machine:

```
Host iuselinux
    HostName your-mac-ip
    User your-username
    LocalForward 1960 localhost:1960
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Then connect with just:

```bash
ssh iuselinux
```

### Troubleshooting

**Port already in use**: Another process is using port 1960. Either stop it or use a different port:

```bash
ssh -L 9000:localhost:1960 user@your-mac-ip
# Then access at http://localhost:9000
```

**Connection refused**: Ensure the iUseLinux server is running on the Mac.

**Permission denied**: Check your SSH key is added or use password auth.

## Remote Access via Tailscale

[Tailscale](https://tailscale.com/) creates a secure mesh VPN that's easier to set up than traditional SSH tunnels. Your Mac acts as the host and other devices on your tailnet can connect to it.

### Setup

1. Install Tailscale on both machines:
   - Mac (server): Download from [tailscale.com](https://tailscale.com/download/mac) or `brew install tailscale`
   - Remote machine: See [download page](https://tailscale.com/download) for your OS

2. Sign in on both machines:
   ```bash
   tailscale up
   ```

3. Find your Mac's Tailscale IP or hostname:
   ```bash
   tailscale ip -4
   # Example: 100.64.0.1

   tailscale status
   # Shows your machine name, e.g., "macbook" -> access via macbook.tailnet-name.ts.net
   ```

### Option 1: Bind to Tailscale Interface Only (Recommended)

Bind the server specifically to your Tailscale IP so only tailnet devices can connect:

```bash
# Get your Tailscale IP
tailscale ip -4
# Example: 100.64.0.1

# On Mac - bind to Tailscale interface only
iuselinux --host 100.64.0.1
```

Then access from any device on your tailnet:
- `http://100.64.0.1:1960` or `http://your-mac.tailnet-name.ts.net:1960`

**Security note**: Binding to the Tailscale IP (100.x.x.x) ensures only devices on your tailnet can connect. This is much safer than `--host 0.0.0.0` which exposes the server on all interfaces (local network, etc.).

For additional security, set an API token:

```bash
iuselinux --host 100.64.0.1 --api-token YOUR_SECRET_TOKEN
```

### Option 2: Tailscale Serve (HTTPS with Magic DNS) - Recommended

Use the built-in Tailscale integration for automatic HTTPS and lifecycle management:

```bash
# Install as a service with Tailscale enabled
iuselinux service install --tailscale
```

This gives you:
- HTTPS URL like `https://your-mac.tailnet-name.ts.net`
- Automatic TLS certificates
- No need to remember port numbers
- **Tailscale serve lifecycle tied to iuselinux** - it starts and stops with the service

Access from any device on your tailnet:
- `https://your-mac.tailnet-name.ts.net`

To check status:
```bash
iuselinux service status
```

To uninstall (this also disables Tailscale serve):
```bash
iuselinux service uninstall
```

#### Important: Tailscale Lifecycle Management

When you use `--tailscale`, iuselinux manages the Tailscale serve lifecycle:

- **Tailscale serve starts** when iuselinux starts
- **Tailscale serve stops** when iuselinux stops (graceful shutdown, crash, or uninstall)
- **Uninstalling clears Tailscale config** - no dangling ports left exposed

This is a security feature. If iuselinux stops for any reason, Tailscale won't continue exposing the port to your tailnet.

#### Manual Tailscale Control

You can also enable/disable Tailscale serve via the web UI settings, or via API:

```bash
# Enable (also saves config for restarts)
curl -X POST "http://localhost:1960/service/tailscale/enable?port=1960"

# Disable (also clears config)
curl -X POST "http://localhost:1960/service/tailscale/disable"
```

#### Legacy Manual Setup (Not Recommended)

If you prefer to manage Tailscale serve separately (not recommended as it decouples lifecycles):

```bash
# Start iuselinux without --tailscale
iuselinux service install

# Manually run tailscale serve with --bg for persistence
tailscale serve --bg 1960
```

**Warning**: With this approach, if you uninstall iuselinux, Tailscale will continue serving port 1960. You must manually run `tailscale serve off` to clean up.

### Option 3: SSH Tunnel over Tailscale (Overkill)

If you're paranoid and want double encryption (Tailscale already encrypts everything):

```bash
# On Mac - start server on localhost only
iuselinux

# On remote machine - create tunnel over Tailscale
ssh -L 1960:localhost:1960 user@100.64.0.1
```

Then access at `http://localhost:1960` on the remote machine.

### Security Notes

- Tailscale traffic is encrypted end-to-end
- Only devices in your tailnet can connect
- Consider enabling [Tailscale ACLs](https://tailscale.com/kb/1018/acls) for fine-grained access control
- The `tailscale serve` option provides HTTPS automatically
- Always use `--api-token` when binding to 0.0.0.0 for an extra layer of security

## Remote Access via WireGuard

For self-hosted VPN, use [WireGuard](https://www.wireguard.com/).

### Setup

1. Install WireGuard on both machines:
   - Mac: `brew install wireguard-tools`
   - Linux: `sudo apt install wireguard`

2. Generate keys on both machines:
   ```bash
   wg genkey | tee privatekey | wg pubkey > publickey
   ```

3. Create `/etc/wireguard/wg0.conf` on your Mac:
   ```ini
   [Interface]
   PrivateKey = <mac-private-key>
   Address = 10.0.0.1/24
   ListenPort = 51820

   [Peer]
   PublicKey = <remote-public-key>
   AllowedIPs = 10.0.0.2/32
   ```

4. Create `/etc/wireguard/wg0.conf` on remote machine:
   ```ini
   [Interface]
   PrivateKey = <remote-private-key>
   Address = 10.0.0.2/24

   [Peer]
   PublicKey = <mac-public-key>
   Endpoint = your-mac-public-ip:51820
   AllowedIPs = 10.0.0.1/32
   PersistentKeepalive = 25
   ```

5. Start WireGuard:
   ```bash
   sudo wg-quick up wg0
   ```

6. Access the gateway via SSH tunnel over WireGuard:
   ```bash
   ssh -L 1960:localhost:1960 user@10.0.0.1
   ```
   Then open `http://localhost:1960`

### Port Forwarding

If your Mac is behind a router, forward UDP port 51820 to your Mac's local IP.

## API Endpoints

### Messages & Chats
- `GET /chats` - List conversations (supports `limit`)
- `GET /messages` - Get messages (`chat_id`, `limit`, `after_rowid`, `before_rowid`)
- `GET /search` - Search messages (`q`, `chat_id`, `limit`, `offset`)
- `GET /poll` - Poll for new messages (`after_rowid`, `chat_id`, `limit`)
- `POST /send` - Send a text message
- `POST /send-with-attachment` - Send a file attachment
- `WebSocket /ws` - Real-time updates (`chat_id`, `token` for auth)

### Attachments
- `GET /attachments/{id}` - Get attachment file (auto-converts HEIC to WebP)
- `GET /attachments/{id}/thumbnail` - Get video thumbnail (requires ffmpeg)
- `GET /attachments/{id}/stream` - Stream/transcode video to MP4

### Contacts
- `GET /contacts/{handle}` - Look up contact info
- `GET /contacts/{handle}/image` - Get contact photo

### Configuration
- `GET /config` - Get all settings
- `PUT /config` - Update settings
- `GET /config/defaults` - Get default values

### Service Management
- `GET /service/status` - Service and Tailscale status
- `POST /service/install` - Install LaunchAgent
- `POST /service/uninstall` - Uninstall service
- `POST /service/tailscale/enable` - Enable Tailscale serve
- `POST /service/tailscale/disable` - Disable Tailscale serve

### System
- `GET /health` - Health check with ffmpeg/contacts status
- `GET /version` - Current and latest version info
- `POST /version/check` - Force check for updates
- `POST /version/update` - Trigger update
- `GET /sleep/status` - Check sleep prevention status
- `POST /sleep/allow` - Temporarily allow sleep
- `POST /sleep/prevent` - Re-engage sleep prevention

## Configuration

Settings are accessible via the web UI (Settings → General) or the `/config` API. Available options:

| Setting | Default | Description |
|---------|---------|-------------|
| `theme` | `auto` | UI theme: `auto`, `light`, or `dark` |
| `prevent_sleep` | `true` | Keep Mac awake while running |
| `api_token` | `""` | API token for authentication (empty = no auth) |
| `notifications_enabled` | `true` | Browser notifications for new messages |
| `notification_sound_enabled` | `true` | Play sound with notifications |
| `use_custom_notification_sound` | `false` | Use uploaded custom sound |
| `auto_update_enabled` | `true` | Auto-install updates |
| `update_check_interval` | `86400` | Seconds between update checks |
| `custom_css` | `""` | Custom CSS for UI styling |
| `websocket_poll_interval` | `1.0` | Seconds between message polls |
| `thumbnail_cache_ttl` | `86400` | Video thumbnail cache duration |
| `thumbnail_timestamp` | `3.0` | Seconds into video for thumbnail |
| `contact_cache_ttl` | `86400` | Contact info cache duration |
| `log_level` | `WARNING` | Logging verbosity |

## macOS Permissions

iUseLinux requires certain macOS permissions to function fully.

### Full Disk Access (Required)

The app needs to read the iMessage database located at `~/Library/Messages/chat.db`.

1. Open **System Settings** → **Privacy & Security** → **Full Disk Access**
2. Click the **+** button and add **Terminal** (or your terminal app)
3. Restart Terminal

### Contacts Access (Automatic via Full Disk Access)

Contact names and photos are resolved by reading the macOS AddressBook database directly. This uses the same **Full Disk Access** permission required for the iMessage database - no separate Contacts permission is needed.

If contacts aren't showing, ensure Full Disk Access is properly configured (see above).

### Automation (Required for Sending)

To send messages, the app uses AppleScript to control Messages.app:

1. When you first send a message, macOS will prompt for permission
2. Click **OK** to allow Terminal to control Messages.app
3. If denied, go to **System Settings** → **Privacy & Security** → **Automation**
4. Enable **Terminal** → **Messages**

## Optional Dependencies

### FFmpeg (for video features)

Video thumbnails and MOV→MP4 transcoding require ffmpeg:

```bash
brew install ffmpeg
```

Without ffmpeg, videos will still display but thumbnails and streaming won't be available. The `/health` endpoint shows whether ffmpeg is detected.

## Manual Removal

To completely remove iUseLinux from your system:

1. **Uninstall the service** (if installed):
   ```bash
   uvx iuselinux service uninstall
   ```

2. **Remove application data and logs**:
   ```bash
   rm -rf ~/Library/Application\ Support/iuselinux/
   rm -rf ~/Library/Logs/iuselinux/
   ```

3. **Remove the app bundle** (if present):
   ```bash
   rm -rf ~/Applications/iUseLinux.app/
   ```

4. **Remove the uv tool installation** (if installed via `uv tool install`):
   ```bash
   uv tool uninstall iuselinux
   ```

5. **Revoke permissions** (optional):
   - Open **System Settings** → **Privacy & Security** → **Full Disk Access**
   - Remove any iUseLinux-related entries (Terminal, iUseLinux Service.app, etc.)
   - Similarly check **Automation** and remove Terminal → Messages if desired