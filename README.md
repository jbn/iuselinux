Start the server with:

```bash
uv run uvicorn imessage_gateway.api:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 in your browser.

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

## API Endpoints

- `GET /chats` - List conversations
- `GET /messages?chat_id=N` - Get messages from a chat
- `GET /poll?after_rowid=N` - Poll for new messages (use for live updates)
- `POST /send` - Send a message
- `GET /attachments/{id}` - Get attachment file (images, videos, etc.)
- `GET /health` - Health check