# iuselinux

A web interface for reading and sending iMessages on macOS.

## Installation

```bash
uv pip install iuselinux
```

For development (includes pytest):

```bash
uv pip install -e ".[dev]"
```

## Initial Setup

**Important:** Before running iUseLinux for the first time, you must grant **Full Disk Access** permission to your terminal app. This allows iUseLinux to read the iMessage database.

1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
2. Click the **+** button and add your terminal app (Terminal, iTerm2, VS Code, etc.)
3. **Restart your terminal** for the permission to take effect

Without this permission, iUseLinux will show an error page explaining how to fix it.

## Usage

### Web Interface

Start the server on your Mac:

```bash
iuselinux
```

Then open http://127.0.0.1:8000 in your browser.

## Features

- View all conversations and messages
- Send messages via the web UI
- Real-time updates via WebSocket
- Attachment support (images, videos with auto-conversion)
- Vim keybindings (optional)
- Custom CSS theming
- API token authentication (optional)
- Prevents Mac from sleeping while running (configurable)

## Remote Access via SSH Tunnel

The API binds to `127.0.0.1` by default for security. To access it remotely, use an SSH tunnel.

### From your remote machine

```bash
ssh -L 8000:localhost:8000 user@your-mac-ip
```

This forwards your remote machine's `localhost:8000` to the Mac's `localhost:8000`.

Now access the API at `http://localhost:8000` from your remote machine.

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
    -L 8000:localhost:8000 user@your-mac-ip
```

### SSH config shortcut

Add to `~/.ssh/config` on your remote machine:

```
Host iuselinux
    HostName your-mac-ip
    User your-username
    LocalForward 8000 localhost:8000
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Then connect with just:

```bash
ssh iuselinux
```

### Troubleshooting

**Port already in use**: Another process is using port 8000. Either stop it or use a different port:

```bash
ssh -L 9000:localhost:8000 user@your-mac-ip
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
iuselinux --host 100.64.0.1 --port 8000
```

Then access from any device on your tailnet:
- `http://100.64.0.1:8000` or `http://your-mac.tailnet-name.ts.net:8000`

**Security note**: Binding to the Tailscale IP (100.x.x.x) ensures only devices on your tailnet can connect. This is much safer than `--host 0.0.0.0` which exposes the server on all interfaces (local network, etc.).

For additional security, set an API token:

```bash
iuselinux --host 100.64.0.1 --port 8000 --api-token YOUR_SECRET_TOKEN
```

### Option 2: Tailscale Serve (HTTPS with Magic DNS)

Use `tailscale serve` to expose the server with automatic HTTPS and a clean URL:

```bash
# On Mac - start the server on localhost
iuselinux --host 127.0.0.1 --port 8000

# In another terminal - expose via Tailscale
tailscale serve 8000
```

This gives you:
- HTTPS URL like `https://your-mac.tailnet-name.ts.net`
- Automatic TLS certificates
- No need to remember port numbers

Access from any device on your tailnet:
- `https://your-mac.tailnet-name.ts.net`

To stop serving:
```bash
tailscale serve off
```

To check current serve status:
```bash
tailscale serve status
```

### Option 3: SSH Tunnel over Tailscale (Overkill)

If you're paranoid and want double encryption (Tailscale already encrypts everything):

```bash
# On Mac - start server on localhost only
iuselinux --host 127.0.0.1 --port 8000

# On remote machine - create tunnel over Tailscale
ssh -L 8000:localhost:8000 user@100.64.0.1
```

Then access at `http://localhost:8000` on the remote machine.

### Auto-Serve on Startup

To automatically start both iuselinux and `tailscale serve` when you log in:

**Using launchd (recommended for macOS):**

Create `~/Library/LaunchAgents/com.iuselinux.server.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.iuselinux.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/iuselinux</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/iuselinux.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/iuselinux.err</string>
</dict>
</plist>
```

Load it with:
```bash
launchctl load ~/Library/LaunchAgents/com.iuselinux.server.plist
```

Then set up `tailscale serve` to persist (it remembers the configuration):
```bash
tailscale serve --bg 8000
```

The `--bg` flag makes it persist across Tailscale restarts.

**Using a shell script:**

Create `~/bin/start-iuselinux.sh`:
```bash
#!/bin/bash
# Start iuselinux server
iuselinux --host 127.0.0.1 --port 8000 &

# Wait for server to start
sleep 2

# Expose via Tailscale
tailscale serve 8000
```

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
   ssh -L 8000:localhost:8000 user@10.0.0.1
   ```
   Then open `http://localhost:8000`

### Port Forwarding

If your Mac is behind a router, forward UDP port 51820 to your Mac's local IP.

## API Endpoints

- `GET /chats` - List conversations
- `GET /messages?chat_id=N` - Get messages from a chat
- `GET /poll?after_rowid=N` - Poll for new messages (use for live updates)
- `POST /send` - Send a message
- `GET /attachments/{id}` - Get attachment file (images, videos, etc.)
- `GET /health` - Health check

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