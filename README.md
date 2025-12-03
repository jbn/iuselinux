# iMessage Gateway

A web interface for reading and sending iMessages on macOS.

## Installation

```bash
uv pip install -e .
```

For development (includes pytest):

```bash
uv pip install -e ".[dev]"
```

## Usage

Start the server:

```bash
imessage-gateway
```

Or run directly with uvicorn:

```bash
uv run uvicorn imessage_gateway.api:app --host 127.0.0.1 --port 8000
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
Host imessage-gateway
    HostName your-mac-ip
    User your-username
    LocalForward 8000 localhost:8000
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Then connect with just:

```bash
ssh imessage-gateway
```

### Troubleshooting

**Port already in use**: Another process is using port 8000. Either stop it or use a different port:

```bash
ssh -L 9000:localhost:8000 user@your-mac-ip
# Then access at http://localhost:9000
```

**Connection refused**: Ensure the iMessage Gateway server is running on the Mac.

**Permission denied**: Check your SSH key is added or use password auth.

## Remote Access via Tailscale

[Tailscale](https://tailscale.com/) creates a secure mesh VPN that's easier to set up than traditional SSH tunnels.

### Setup

1. Install Tailscale on both machines:
   - Mac (server): Download from [tailscale.com](https://tailscale.com/download/mac) or `brew install tailscale`
   - Remote machine: See [download page](https://tailscale.com/download) for your OS

2. Sign in on both machines:
   ```bash
   tailscale up
   ```

3. Find your Mac's Tailscale IP:
   ```bash
   tailscale ip -4
   # Example: 100.64.0.1
   ```

4. Modify the server to listen on Tailscale interface (optional):

   By default, the server binds to `127.0.0.1`. To access via Tailscale, you can either:

   **Option A**: Use SSH tunnel over Tailscale (recommended - keeps localhost binding):
   ```bash
   ssh -L 8000:localhost:8000 user@100.64.0.1
   ```

   **Option B**: Bind to all interfaces (less secure):
   ```bash
   uv run uvicorn imessage_gateway.api:app --host 0.0.0.0 --port 8000
   ```
   Then access at `http://100.64.0.1:8000`

### Security Notes

- Tailscale traffic is encrypted end-to-end
- Only devices in your Tailscale network can connect
- Consider enabling [Tailscale ACLs](https://tailscale.com/kb/1018/acls) for fine-grained access control

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