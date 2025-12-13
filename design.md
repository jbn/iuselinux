# building a remote-access imessage gateway on macos

short version: you can’t run “real” imessage on a server, but you *can* turn your mac into a little imessage gateway and talk to it remotely.

on macos, you basically have three building blocks:

1. **reading** messages = talking to the local sqlite db (`chat.db`)  
2. **sending** messages = scripting the `Messages.app` (applescript)  
3. **remote access** = wrapping those in some api (http/websocket/etc.) that you hit from elsewhere

i’ll walk through an architecture that actually works and what the code roughly looks like.

---

## 1. where imessage lives on macos

the messages app keeps a sqlite db here:

```text
~/Library/Messages/chat.db
```

that db has tables like `chat`, `message`, `handle`, and a join table `chat_message_join`. you can `SELECT` from it like any normal sqlite db (read-only is safest).

example (in python) to just peek at the last 10 messages across all chats:

```python
import sqlite3
from pathlib import Path

db_path = Path.home() / "Library" / "Messages" / "chat.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

query = """
SELECT
  message.ROWID as id,
  datetime(message.date / 1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') as ts,
  message.text,
  handle.id as handle_id
FROM message
LEFT JOIN handle ON message.handle_id = handle.ROWID
ORDER BY message.date DESC
LIMIT 10;
"""

for row in cur.execute(query):
    print(row["ts"], row["handle_id"], ":", row["text"])
```

notes:

- the date is in “mac absolute time” (nanoseconds since 2001-01-01), hence that evil conversion.
- you probably want **read-only** access: `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` so you don’t corrupt it.
- you’ll need full disk access / permissions for your script in macos privacy & security.

---

## 2. sending messages via applescript

apple doesn’t give you a nice public “send imessage via api” thing, but `Messages.app` is scriptable.

you can send via applescript directly, or call applescript from python/node/whatever.

**basic applescript**:

```applescript
on send_imessage(phoneNumber, theText)
    tell application "Messages"
        set theService to 1st service whose service type = iMessage
        set theBuddy to buddy phoneNumber of theService
        send theText to theBuddy
    end tell
end send_imessage

send_imessage("+15551234567", "hello from a script")
```

from python:

```python
import subprocess
import textwrap

def send_imessage(recipient, text):
    script = textwrap.dedent(f'''
    on run argv
        set target to item 1 of argv
        set msg to item 2 of argv
        tell application "Messages"
            set theService to 1st service whose service type = iMessage
            set theBuddy to buddy target of theService
            send msg to theBuddy
        end tell
    end run
    ''')
    subprocess.run(
        ["osascript", "-e", script, recipient, text],
        check=True
    )

# example:
send_imessage("+15551234567", "this came from a python script")
```

caveats:

- this uses whatever account is signed into `Messages.app` on that mac.
- it only works while the mac is on, awake, and logged in.
- apple can change scripting behavior, but this approach has survived many os versions.

---

## 3. wrapping it into a local api (so you can reach it remotely)

now glue (1) and (2) into a tiny local service.

say, a `FastAPI` server that exposes:

- `GET /conversations` → list chats  
- `GET /messages?chat_id=…` → read messages  
- `POST /send` → send a message

rough sketch:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3, subprocess, textwrap
from pathlib import Path

app = FastAPI()

DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

def db_conn():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

class SendRequest(BaseModel):
    to: str  # phone or email
    text: str

def send_imessage(recipient, text):
    script = textwrap.dedent('''
    on run argv
        set target to item 1 of argv
        set msg to item 2 of argv
        tell application "Messages"
            set theService to 1st service whose service type = iMessage
            set theBuddy to buddy target of theService
            send msg to theBuddy
        end tell
    end run
    ''')
    subprocess.run(
        ["osascript", "-e", script, recipient, text],
        check=True
    )

@app.get("/chats")
def list_chats():
    conn = db_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    q = """
    SELECT chat.ROWID as id,
           chat.display_name as name
    FROM chat
    ORDER BY id DESC
    LIMIT 100;
    """
    chats = [dict(row) for row in cur.execute(q)]
    conn.close()
    return chats

@app.get("/messages")
def get_messages(chat_id: int, limit: int = 50):
    conn = db_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    q = """
    SELECT
      message.ROWID as id,
      datetime(message.date / 1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') as ts,
      message.is_from_me,
      message.text
    FROM chat_message_join
    JOIN message ON message.ROWID = chat_message_join.message_id
    WHERE chat_message_join.chat_id = ?
    ORDER BY message.date DESC
    LIMIT ?;
    """
    cur.execute(q, (chat_id, limit))
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages

@app.post("/send")
def send(req: SendRequest):
    try:
        send_imessage(req.to, req.text)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="failed to send imessage") from e
    return {"status": "ok"}
```

run that with uvicorn:

```bash
pip install fastapi uvicorn pydantic
uvicorn imessage_api:app --host 0.0.0.0 --port 8000
```

now this mac is an imessage “gateway”:

- from your phone / another machine / a server, you can hit:
  - `GET http://your-mac-ip:8000/messages?chat_id=1`
  - `POST http://your-mac-ip:8000/send` with `{ "to":"+1555...","text":"yo" }`

---

## 4. making it remotely reachable (safely)

this is where it’s easy to turn your laptop into a disaster if you’re careless.

options:

1. **ssh tunnel** (my strong recommendation)  
   - keep api bound to `127.0.0.1:8000`.  
   - from remote machine:  
     ```bash
     ssh -L 8000:localhost:8000 you@your-mac
     ```  
   - now `http://localhost:8000` on the remote machine is tunneled to your mac securely.

2. **vpn**  
   - wireguard / tailscale etc.  
   - mac & remote device share a private overlay network.

3. **public exposure (nginx, reverse proxy, etc.)**  
   - only if you *really* know what you’re doing.  
   - must add proper auth (tokens, oauth, mTLS, etc.). absolutely do not ship a naked send-imessage endpoint to the internet.

---

## 5. dealing with “live” updates

reading from `chat.db` gives you history, but not push-style updates. basic patterns:

- **polling**: every `N` seconds, ask for “messages newer than last_seen_id`.  
- **fs event watching**: use `fsevents`/`watchdog` in python to watch the db file and repoll on change.  
- or accept that this is a “pull” interface and keep it simple.

example polling query:

```sql
SELECT ... FROM message
WHERE ROWID > ?
ORDER BY ROWID ASC;
```

keep `last_rowid` in your client and increment.

---

## 6. guardrails & ethics (important)

just to be explicit about the boundaries:

- this is **only** legitimate for *your own* account on *your own* mac.  
- don’t use this to read someone else’s messages, bypass corporate monitoring, etc.  
- give your process **minimal permissions** and lock down any remote access (tunnel/vpn, auth, firewall). an attacker who gets this api basically gets your entire personal life.

---

## 7. if you want to go deeper

once the basics work, fun directions:

- build a nicer client (react / mobile app) talking to this api.  
- add search over messages (sqlite full-text, or export into something fancier).  
- mark certain chats as “mirrored” and sync them into whatever other system you like (slack, discord, etc.).  
- wrap it all in a systemd/launchd service so it starts on login.
