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

## macOS Permissions

iMessage Gateway requires certain macOS permissions to function fully.

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

## Technical Notes: macOS Contacts Access

This section documents the technical challenges and solutions for accessing macOS Contacts from a Python application. This information is preserved for future reference.

### The Problem: macOS TCC (Transparency, Consent, and Control)

macOS protects sensitive data (Contacts, Photos, etc.) using the TCC system. Apps must be granted explicit permission to access this data. However, **command-line tools have significant limitations**:

1. **No permission dialogs**: When a CLI tool calls `CNContactStore.requestAccess()`, macOS silently denies the request instead of showing a dialog
2. **Permission inheritance doesn't work**: Even if Terminal.app has Contacts permission, subprocess-spawned binaries don't inherit it
3. **Bundle ID signing is insufficient**: Ad-hoc code signing with a bundle identifier doesn't grant TCC permissions to CLI tools
4. **App bundles require proper launch**: A binary inside an `.app` bundle only gets its TCC permissions when launched via LaunchServices (`open` command), not when executed directly

### Approaches That Don't Work

1. **Swift/Objective-C binary using CNContactStore**: The binary runs fine but `CNContactStore.authorizationStatus()` returns `.notDetermined`, and `requestAccess()` silently fails with "Access Denied"

2. **Granting permission to Terminal/VS Code**: Adding your terminal app to Privacy & Security → Contacts doesn't help because subprocess-spawned processes don't inherit the permission

3. **Creating an app bundle with NSContactsUsageDescription**: The app bundle can request and receive permission when opened via `open /path/to/App.app`, but executing the binary directly (`/path/to/App.app/Contents/MacOS/binary`) doesn't use those permissions

4. **Code signing with bundle identifier**: Even signing the binary with `codesign --identifier "com.example.app"` to match a granted TCC entry doesn't work for CLI execution

### The Solution: Direct SQLite Access

The macOS AddressBook is stored in a SQLite database at:
```
~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb
```

This database is accessible via **Full Disk Access** - the same permission already required for reading the iMessage database (`~/Library/Messages/chat.db`).

**Key tables:**
- `ZABCDRECORD` - Contact records (first name, last name, nickname, thumbnail image)
- `ZABCDPHONENUMBER` - Phone numbers linked to contacts via `ZOWNER` foreign key
- `ZABCDEMAILADDRESS` - Email addresses linked to contacts via `ZOWNER` foreign key

**Contact photos:**

Contact photos are stored in `ZABCDRECORD.ZTHUMBNAILIMAGEDATA` with a prefix byte indicating storage format:
- `0x01` prefix: Inline JPEG data (remaining bytes are the JPEG image)
- `0x02` prefix: UUID reference to external file (remaining bytes are null-terminated UUID string)

For `0x02` references, the actual image is stored as a JPEG file in:
```
~/Library/Application Support/AddressBook/Sources/*/.AddressBook-v22_SUPPORT/_EXTERNAL_DATA/<UUID>
```

Note: The older `ZABCDLIKENESS` table is typically empty on modern macOS versions.

**Phone number matching:**
```sql
SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK
FROM ZABCDRECORD r
JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', ''), '+', '') LIKE '%' || ?
   OR ? LIKE '%' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', ''), '+', '')
```

**Email matching:**
```sql
SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK
FROM ZABCDRECORD r
JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
WHERE LOWER(e.ZADDRESS) = LOWER(?)
```

### Benefits of SQLite Approach

1. **No separate permission needed** - Uses existing Full Disk Access
2. **Simpler architecture** - Pure Python, no subprocess calls, no external binaries
3. **Faster** - Direct database queries vs spawning processes
4. **Reliable** - No macOS permission quirks to work around
5. **Portable** - Works regardless of which terminal/IDE launches the server

### Alternative: PyObjC

If you need to use the CNContactStore API (e.g., for write access), you could use PyObjC:
```bash
pip install pyobjc-framework-Contacts
```

However, PyObjC has the same TCC permission issues as Swift binaries when run from CLI. It would only work if:
- The Python process is launched from an app that has Contacts permission
- Or the Python script is bundled into a proper .app with py2app/PyInstaller

For read-only contact lookup, the SQLite approach is simpler and more reliable.