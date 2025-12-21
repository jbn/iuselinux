"""FastAPI server for iUseLinux."""

import atexit
import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path

import asyncio

logger = logging.getLogger("iuselinux.api")

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image
import pillow_heif

# Register HEIF/HEIC support with Pillow
pillow_heif.register_heif_opener()


# FFmpeg availability detection
def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system."""
    return shutil.which("ffmpeg") is not None


def _check_ffprobe() -> bool:
    """Check if ffprobe is available on the system."""
    return shutil.which("ffprobe") is not None


FFMPEG_AVAILABLE = _check_ffmpeg()
FFPROBE_AVAILABLE = _check_ffprobe()

# Thumbnail cache directory (thumbnails are small, worth caching on disk)
CACHE_DIR = Path(tempfile.gettempdir()) / "iuselinux_cache"
CACHE_DIR.mkdir(exist_ok=True)


# Rate limiting for send endpoint
RATE_LIMIT_MESSAGES = 10  # Max messages per window
RATE_LIMIT_WINDOW = 60  # Window in seconds
_send_timestamps: deque[float] = deque()

from .db import FullDiskAccessError, check_db_access, get_db_path
from .messages import get_chats, get_messages, get_attachment, search_messages, Chat, Message, Attachment
from .sender import send_imessage, send_imessage_with_file, SendResult
from .config import get_config, get_config_value, set_config_value, update_config, DEFAULTS as CONFIG_DEFAULTS
from .contacts import resolve_contact, is_available as contacts_available, ContactInfo

# Track database accessibility at startup (can be updated via /check-access endpoint)
_db_accessible: bool | None = None

# Global caffeinate process handle for sleep prevention
_caffeinate_proc: subprocess.Popen[bytes] | None = None
_caffeinate_atexit_registered: bool = False


def _cleanup_caffeinate_atexit() -> None:
    """Atexit handler to ensure caffeinate is stopped on process exit."""
    stop_caffeinate()


def start_caffeinate(mode: str | None = None) -> bool:
    """Start caffeinate process to prevent system sleep.

    Args:
        mode: Sleep prevention mode - "ac_power" (-s) or "always" (-i).
              If None, reads from config. Default is "ac_power".

    Returns True if caffeinate was started successfully, False otherwise.
    """
    global _caffeinate_proc, _caffeinate_atexit_registered

    if _caffeinate_proc is not None and _caffeinate_proc.poll() is None:
        # Already running
        return True

    # Get mode from config if not provided
    if mode is None:
        mode = get_config().get("sleep_mode", "ac_power")

    # Map mode to caffeinate flag
    # -s: prevent sleep only when on AC power (default, battery-friendly)
    # -i: prevent idle sleep always (even on battery)
    flag = "-s" if mode == "ac_power" else "-i"

    try:
        _caffeinate_proc = subprocess.Popen(
            ["caffeinate", flag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        mode_desc = "on AC power only" if mode == "ac_power" else "always"
        logger.info("Caffeinate started (%s) - preventing system sleep", mode_desc)

        # Register atexit handler to ensure cleanup on process exit (SIGKILL, segfault, etc.)
        if not _caffeinate_atexit_registered:
            atexit.register(_cleanup_caffeinate_atexit)
            _caffeinate_atexit_registered = True

        return True
    except FileNotFoundError:
        logger.warning("caffeinate not found (not on macOS?)")
        return False
    except Exception as e:
        logger.warning("Failed to start caffeinate: %s", e)
        return False


def stop_caffeinate() -> bool:
    """Stop caffeinate process to allow system sleep.

    Returns True if caffeinate was stopped, False if it wasn't running.
    """
    global _caffeinate_proc

    if _caffeinate_proc is None:
        return False

    if _caffeinate_proc.poll() is None:
        # Still running, terminate it
        _caffeinate_proc.terminate()
        try:
            _caffeinate_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _caffeinate_proc.kill()
        logger.info("Caffeinate stopped - allowing system sleep")

    _caffeinate_proc = None
    return True


def is_caffeinate_running() -> bool:
    """Check if caffeinate process is currently running."""
    global _caffeinate_proc
    return _caffeinate_proc is not None and _caffeinate_proc.poll() is None


def _check_and_report_db_access() -> bool:
    """Check database access and report status to stderr if unavailable."""
    global _db_accessible
    _db_accessible = check_db_access()

    if not _db_accessible:
        db_path = get_db_path()
        print(
            "\n"
            "=" * 70 + "\n"
            "ERROR: Full Disk Access permission required\n"
            "=" * 70 + "\n"
            f"\n"
            f"Cannot access iMessage database at:\n"
            f"  {db_path}\n"
            f"\n"
            f"iUseLinux needs Full Disk Access to read your messages.\n"
            f"\n"
            f"To fix this:\n"
            f"  1. Open System Settings (or System Preferences)\n"
            f"  2. Go to Privacy & Security > Full Disk Access\n"
            f"  3. Click the + button\n"
            f"  4. Add your terminal app (Terminal, iTerm2, VS Code, etc.)\n"
            f"  5. Restart your terminal and run iuselinux again\n"
            f"\n"
            f"The web server will start, but you'll see an error page until\n"
            f"Full Disk Access is granted.\n"
            "=" * 70 + "\n",
            file=sys.stderr,
        )

    return _db_accessible


from contextlib import asynccontextmanager
from typing import AsyncGenerator

from . import __version__

# NOTE: Auto-update has been disabled for security reasons (see dangerous_audit.md).
# Updates are now shown via a banner notification and require manual installation.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    yield


app = FastAPI(
    title="iUseLinux",
    description="Read and send iMessages via local API",
    version=__version__,
    lifespan=lifespan,
)

# Static files directory
static_dir = Path(__file__).parent / "static"

# Files that should never be cached (for development and releases)
NO_CACHE_FILES = {"index.html", "app.js", "styles.css"}


@app.get("/static/{file_path:path}")
def serve_static(file_path: str) -> FileResponse:
    """Serve static files with appropriate cache headers."""
    full_path = (static_dir / file_path).resolve()
    # SECURITY FIX: Prevent path traversal attacks.
    # Without this check, requests like '/static/../../../etc/passwd' could
    # access files outside the static directory.
    if not full_path.is_relative_to(static_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine cache headers based on file
    filename = full_path.name
    if filename in NO_CACHE_FILES:
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    else:
        # Cache other static assets (images, fonts, etc.) for 1 day
        headers = {"Cache-Control": "public, max-age=86400"}

    return FileResponse(full_path, headers=headers)


# Config directory for user files (custom sounds, etc.)
from .config import CONFIG_DIR, _ensure_config_dir

# Allowed audio file extensions
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}


def _get_custom_sound_path() -> Path | None:
    """Find the custom notification sound file if it exists."""
    for ext in ALLOWED_AUDIO_EXTENSIONS:
        path = CONFIG_DIR / f"custom-sound{ext}"
        if path.exists():
            return path
    return None


def _delete_custom_sounds() -> None:
    """Delete any existing custom sound files."""
    for ext in ALLOWED_AUDIO_EXTENSIONS:
        path = CONFIG_DIR / f"custom-sound{ext}"
        if path.exists():
            path.unlink()


@app.head("/notification-sound")
@app.get("/notification-sound")
def serve_notification_sound() -> FileResponse:
    """Serve custom notification sound from user's config directory."""
    sound_path = _get_custom_sound_path()
    if not sound_path:
        raise HTTPException(status_code=404, detail="No custom sound configured")

    suffix = sound_path.suffix.lower()
    return FileResponse(sound_path, media_type=f"audio/{suffix[1:]}")


from fastapi import UploadFile, File, Form


@app.post("/notification-sound")
async def upload_notification_sound(file: UploadFile = File(...)) -> dict:
    """Upload a custom notification sound file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Check file extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid audio format. Allowed: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}"
        )

    # Ensure config dir exists
    _ensure_config_dir()

    # Delete any existing custom sounds
    _delete_custom_sounds()

    # Save new sound file
    dest_path = CONFIG_DIR / f"custom-sound{suffix}"
    content = await file.read()

    # Basic size limit (5MB)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    with open(dest_path, "wb") as f:
        f.write(content)

    return {"success": True, "filename": f"custom-sound{suffix}"}


@app.delete("/notification-sound")
def delete_notification_sound() -> dict:
    """Delete custom notification sound."""
    _delete_custom_sounds()
    return {"success": True}

# Authentication
security = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    """Verify API token if authentication is enabled."""
    api_token = get_config_value("api_token")

    # No token configured = no auth required
    if not api_token:
        return

    # Token configured but no credentials provided
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="API token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify token
    if credentials.credentials != api_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Public routes that don't require auth (UI and static assets)
PUBLIC_PATHS = {"/", "/health"}


from typing import Callable, Awaitable
from starlette.responses import Response


@app.middleware("http")
async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Check authentication for API endpoints."""
    path = request.url.path

    # Skip auth for public paths and static files
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)

    # Check if auth is enabled
    api_token = get_config_value("api_token")
    if not api_token:
        return await call_next(request)

    # Verify token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == api_token:
            return await call_next(request)

    # Auth failed
    return JSONResponse(
        status_code=401,
        content={"detail": "API token required"},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(FullDiskAccessError)
async def full_disk_access_handler(
    request: Request, exc: FullDiskAccessError
) -> JSONResponse:
    """Handle missing Full Disk Access permission."""
    return JSONResponse(
        status_code=403,
        content={
            "detail": str(exc),
            "error_type": "full_disk_access_required",
        },
    )


@app.get("/")
def index() -> FileResponse:
    """Serve the main UI or error page if database is inaccessible."""
    global _db_accessible
    # If we haven't checked yet or access was previously denied, recheck
    if _db_accessible is None or not _db_accessible:
        _db_accessible = check_db_access()

    if not _db_accessible:
        return FileResponse(static_dir / "error-no-access.html")
    return FileResponse(static_dir / "index.html")


@app.get("/check-access")
def check_access() -> dict:
    """
    Check if database access is available.

    Used by the error page to poll for access after user grants permission.
    Returns {"accessible": true/false}.
    """
    global _db_accessible
    _db_accessible = check_db_access()
    return {"accessible": _db_accessible}


# Response models
class ContactResponse(BaseModel):
    """Contact information response."""

    handle: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    nickname: str | None = None
    initials: str | None = None
    has_image: bool = False
    image_url: str | None = None  # URL to fetch avatar if available


class ParticipantResponse(BaseModel):
    """Participant info for group chats."""

    handle: str  # Phone number or email
    contact: ContactResponse | None = None  # Resolved contact info


class ChatResponse(BaseModel):
    """Chat/conversation response."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None
    last_message_time: str | None  # ISO format
    last_message_text: str | None = None  # Preview of the last message
    last_message_is_from_me: bool = False  # Whether the last message was from me
    participants: list[str] | None = None  # For group chats (raw handles, for backwards compat)
    participant_contacts: list[ParticipantResponse] | None = None  # For group chats with resolved contacts
    contact: ContactResponse | None = None  # For 1:1 chats


class AttachmentResponse(BaseModel):
    """Attachment metadata response."""

    rowid: int
    guid: str
    mime_type: str | None
    filename: str | None  # Original filename
    total_bytes: int
    url: str  # URL to fetch the attachment content
    thumbnail_url: str | None = None  # URL for video thumbnail (if ffmpeg available)
    stream_url: str | None = None  # URL for transcoded video stream (if ffmpeg available)


class MessageResponse(BaseModel):
    """Message response."""

    rowid: int
    guid: str
    text: str | None
    timestamp: str | None  # ISO format
    is_from_me: bool
    handle_id: str | None
    chat_id: int | None
    tapback_type: str | None = None  # Reaction type: love, like, dislike, laugh, emphasize, question
    associated_guid: str | None = None  # GUID of message this reacts to
    attachments: list[AttachmentResponse] = []
    contact: ContactResponse | None = None  # Resolved contact info for handle


# Validation patterns
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{6,14}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_MESSAGE_LENGTH = 10000


class SendRequest(BaseModel):
    """Request to send a message."""

    recipient: str = Field(..., min_length=1, max_length=320)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: str) -> str:
        v = v.strip()
        # Remove common phone formatting
        normalized = re.sub(r"[\s\-\(\)]", "", v)
        if PHONE_PATTERN.match(normalized):
            return normalized
        if EMAIL_PATTERN.match(v):
            return v
        # Allow full chat GUIDs for group chats (format: iMessage;+;chat123 or SMS;+;chat123)
        if re.match(r"^(iMessage|SMS|RCS);[+-];chat\d+$", v):
            return v
        raise ValueError("recipient must be a valid phone number, email, or chat GUID")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty or whitespace only")
        return v


class SendResponse(BaseModel):
    """Response from sending a message."""

    success: bool
    error: str | None = None


def _contact_to_response(contact: ContactInfo) -> ContactResponse:
    """Convert ContactInfo dataclass to response model."""
    return ContactResponse(
        handle=contact.handle,
        name=contact.name,
        given_name=contact.given_name,
        family_name=contact.family_name,
        nickname=contact.nickname,
        initials=contact.initials,
        has_image=contact.has_image,
        image_url=f"/contacts/{contact.handle}/image" if contact.has_image else None,
    )


def _resolve_handle(handle: str | None) -> ContactResponse | None:
    """Resolve a handle to contact info, if available."""
    if not handle or not contacts_available():
        return None
    contact = resolve_contact(handle)
    # Only return if we found a name (otherwise just the handle echoed back)
    if contact.name:
        return _contact_to_response(contact)
    return None


def _chat_to_response(chat: Chat) -> ChatResponse:
    """Convert Chat dataclass to response model."""
    # Resolve contact for 1:1 chats (identifier is the phone/email)
    contact = _resolve_handle(chat.identifier)

    # Resolve contacts for group chat participants
    participant_contacts = None
    if chat.participants:
        participant_contacts = [
            ParticipantResponse(
                handle=handle,
                contact=_resolve_handle(handle),
            )
            for handle in chat.participants
        ]

    return ChatResponse(
        rowid=chat.rowid,
        guid=chat.guid,
        display_name=chat.display_name,
        identifier=chat.identifier,
        last_message_time=chat.last_message_time.isoformat() if chat.last_message_time else None,
        last_message_text=chat.last_message_text,
        last_message_is_from_me=chat.last_message_is_from_me,
        participants=chat.participants,
        participant_contacts=participant_contacts,
        contact=contact,
    )


def _attachment_to_response(att: Attachment) -> AttachmentResponse:
    """Convert Attachment dataclass to response model."""
    # Check if this is a video that needs transcoding
    is_video = att.mime_type and att.mime_type.startswith("video/")
    needs_transcode = is_video and att.mime_type not in ("video/mp4", "video/webm", "video/ogg")

    thumbnail_url = None
    stream_url = None

    if is_video and FFMPEG_AVAILABLE:
        thumbnail_url = f"/attachments/{att.rowid}/thumbnail"
        if needs_transcode:
            stream_url = f"/attachments/{att.rowid}/stream"

    return AttachmentResponse(
        rowid=att.rowid,
        guid=att.guid,
        mime_type=att.mime_type,
        filename=att.transfer_name,  # Use original filename
        total_bytes=att.total_bytes,
        url=f"/attachments/{att.rowid}",
        thumbnail_url=thumbnail_url,
        stream_url=stream_url,
    )


def _message_to_response(msg: Message) -> MessageResponse:
    """Convert Message dataclass to response model."""
    # Resolve contact for the sender (only for received messages)
    contact = None
    if not msg.is_from_me:
        contact = _resolve_handle(msg.handle_id)

    return MessageResponse(
        rowid=msg.rowid,
        guid=msg.guid,
        text=msg.text,
        timestamp=msg.timestamp.isoformat() if msg.timestamp else None,
        is_from_me=msg.is_from_me,
        handle_id=msg.handle_id,
        chat_id=msg.chat_id,
        tapback_type=msg.tapback_type,
        associated_guid=msg.associated_guid,
        attachments=[_attachment_to_response(a) for a in msg.attachments],
        contact=contact,
    )


@app.get("/chats", response_model=list[ChatResponse])
def list_chats(limit: int = Query(default=100, le=500)) -> list[ChatResponse]:
    """List all chats/conversations."""
    logger.info("Fetching chats (limit=%d)", limit)
    chats = get_chats(limit=limit)
    logger.info("Returning %d chats", len(chats))
    return [_chat_to_response(c) for c in chats]


@app.get("/messages", response_model=list[MessageResponse])
def list_messages(
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    limit: int = Query(default=50, le=500),
    after_rowid: int | None = Query(default=None, description="Only messages after this rowid (for new messages)"),
    before_rowid: int | None = Query(default=None, description="Only messages before this rowid (for pagination)"),
) -> list[MessageResponse]:
    """Fetch messages, optionally filtered by chat."""
    logger.info("Fetching messages (chat_id=%s, limit=%d, after_rowid=%s, before_rowid=%s)", chat_id, limit, after_rowid, before_rowid)
    messages = get_messages(chat_id=chat_id, limit=limit, after_rowid=after_rowid, before_rowid=before_rowid)
    logger.info("Returning %d messages", len(messages))
    return [_message_to_response(m) for m in messages]


class SearchResponse(BaseModel):
    """Response from searching messages."""

    messages: list[MessageResponse]
    total: int  # Number of results returned (may be less than limit if fewer matches)
    has_more: bool  # True if there are more results beyond limit+offset


@app.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Search query string"),
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    limit: int = Query(default=50, le=100, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
) -> SearchResponse:
    """
    Search messages by text content.

    Uses LIKE queries against the read-only chat.db database.
    Results are ordered by date descending (newest first).

    Example:
        GET /search?q=hello&limit=20
        GET /search?q=meeting&chat_id=123&limit=50&offset=50
    """
    logger.info("Searching messages (q=%r, chat_id=%s, limit=%d, offset=%d)", q, chat_id, limit, offset)

    # Fetch limit+1 to detect if there are more results
    messages = search_messages(query=q, chat_id=chat_id, limit=limit + 1, offset=offset)

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    logger.info("Search returned %d results (has_more=%s)", len(messages), has_more)
    return SearchResponse(
        messages=[_message_to_response(m) for m in messages],
        total=len(messages),
        has_more=has_more,
    )


def _check_rate_limit() -> None:
    """Check and enforce rate limit, raises HTTPException if exceeded."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW

    # Remove old timestamps
    while _send_timestamps and _send_timestamps[0] < cutoff:
        _send_timestamps.popleft()

    if len(_send_timestamps) >= RATE_LIMIT_MESSAGES:
        retry_after = int(_send_timestamps[0] - cutoff) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MESSAGES} messages per {RATE_LIMIT_WINDOW}s",
            headers={"Retry-After": str(retry_after)},
        )


class SendErrorType:
    """Error type constants for send failures."""

    RATE_LIMITED = "rate_limited"
    RECIPIENT_NOT_FOUND = "recipient_not_found"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


def _classify_send_error(error: str | None) -> tuple[int, str, str]:
    """
    Classify an AppleScript error into HTTP status, error type, and user message.

    Returns:
        Tuple of (http_status_code, error_type, user_friendly_message)
    """
    if error is None:
        return 500, SendErrorType.UNKNOWN, "Unknown error occurred"

    error_lower = error.lower()

    # Recipient not found errors
    if any(phrase in error_lower for phrase in [
        "can't get buddy",
        "can't get participant",
        "not found",
        "invalid phone",
        "invalid email",
    ]):
        return 404, SendErrorType.RECIPIENT_NOT_FOUND, (
            "Recipient not found. Ensure the phone number or email is registered with iMessage."
        )

    # Messages.app not running or iMessage not signed in
    if any(phrase in error_lower for phrase in [
        "can't get service",
        "can't get account",
        "no account",
        "not signed in",
        "connection invalid",
    ]):
        return 503, SendErrorType.SERVICE_UNAVAILABLE, (
            "iMessage service unavailable. Ensure Messages.app is running and signed in."
        )

    # Timeout
    if "timeout" in error_lower:
        return 504, SendErrorType.TIMEOUT, (
            "Request timed out. Messages.app may be unresponsive."
        )

    # Default to unknown error
    return 500, SendErrorType.UNKNOWN, error


class SendErrorResponse(BaseModel):
    """Detailed error response for send failures."""

    success: bool = False
    error: str
    error_type: str
    detail: str | None = None  # Original error for debugging


@app.post("/send", response_model=SendResponse, responses={
    404: {"model": SendErrorResponse, "description": "Recipient not found"},
    429: {"description": "Rate limit exceeded"},
    503: {"model": SendErrorResponse, "description": "iMessage service unavailable"},
    504: {"model": SendErrorResponse, "description": "Request timed out"},
})
def send_message(request: SendRequest) -> SendResponse:
    """Send an iMessage."""
    logger.info("Sending message to %s (length=%d)", request.recipient, len(request.message))
    _check_rate_limit()

    result = send_imessage(request.recipient, request.message)
    if not result.success:
        status_code, error_type, user_message = _classify_send_error(result.error)
        logger.warning("Send failed: %s (type=%s)", user_message, error_type)
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": user_message,
                "error_type": error_type,
                "detail": result.error if result.error != user_message else None,
            },
        )

    logger.info("Message sent successfully to %s", request.recipient)
    _send_timestamps.append(time.time())
    return SendResponse(success=True)


# File upload limits
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
MIN_FREE_DISK_SPACE = 1024 * 1024 * 1024  # 1 GB minimum free space buffer


def _check_disk_space(required_bytes: int, path: Path | None = None) -> bool:
    """Check if enough disk space is available.

    Args:
        required_bytes: Number of bytes we need to write
        path: Path to check (uses /tmp if None)

    Returns:
        True if enough space available, False otherwise
    """
    check_path = path or Path(tempfile.gettempdir())
    try:
        usage = shutil.disk_usage(check_path)
        return usage.free > (required_bytes + MIN_FREE_DISK_SPACE)
    except OSError:
        # If we can't check, allow the write and let it fail naturally
        return True


ALLOWED_FILE_TYPES = {
    # Images
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif",
    # Videos
    "video/mp4", "video/quicktime", "video/mpeg", "video/webm",
    # Audio
    "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg",
    # Documents
    "application/pdf",
}

# Temp directory for uploads
UPLOAD_DIR = Path(tempfile.gettempdir()) / "iuselinux_uploads"


def _ensure_upload_dir() -> None:
    """Ensure the upload directory exists."""
    UPLOAD_DIR.mkdir(exist_ok=True)


def _cleanup_old_uploads(max_age_seconds: int = 3600) -> None:
    """Remove files older than max_age_seconds from upload directory."""
    if not UPLOAD_DIR.exists():
        return
    cutoff = time.time() - max_age_seconds
    for file_path in UPLOAD_DIR.iterdir():
        if file_path.is_file() and file_path.stat().st_mtime < cutoff:
            try:
                file_path.unlink()
            except OSError:
                pass


@app.post("/send-with-attachment", response_model=SendResponse, responses={
    400: {"description": "Invalid file or request"},
    404: {"model": SendErrorResponse, "description": "Recipient not found"},
    413: {"description": "File too large"},
    429: {"description": "Rate limit exceeded"},
    503: {"model": SendErrorResponse, "description": "iMessage service unavailable"},
})
async def send_with_attachment(
    recipient: str = Form(...),
    message: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> SendResponse:
    """
    Send a file attachment via iMessage.

    - recipient: Phone number, email, or chat GUID
    - message: Optional text message to send with the file
    - file: The file to send (multipart/form-data)
    """
    logger.info("Sending attachment to %s: %s", recipient, file.filename)

    # Validate recipient format (reuse logic from SendRequest)
    recipient = recipient.strip()
    normalized = re.sub(r"[\s\-\(\)]", "", recipient)
    if not (PHONE_PATTERN.match(normalized) or
            EMAIL_PATTERN.match(recipient) or
            re.match(r"^(iMessage|SMS|RCS);[+-];chat\d+$", recipient)):
        raise HTTPException(status_code=400, detail="Invalid recipient format")

    # Normalize phone numbers
    if PHONE_PATTERN.match(normalized):
        recipient = normalized

    # Check rate limit
    _check_rate_limit()

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Check file size using content-length header or by reading
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024*1024)} MB)")

    # Check disk space before writing (prevents /tmp exhaustion)
    if not _check_disk_space(len(content)):
        raise HTTPException(
            status_code=507,
            detail="Insufficient disk space. Please free up space and try again."
        )

    # Check content type
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_FILE_TYPES:
        # Be permissive - allow unknown types but warn
        logger.warning("Unknown content type: %s for file %s", content_type, file.filename)

    # Clean up old uploads periodically
    _cleanup_old_uploads()

    # Ensure upload directory exists
    _ensure_upload_dir()

    # Save to temp file with unique name
    file_ext = Path(file.filename).suffix or ""
    temp_filename = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}{file_ext}"
    temp_path = UPLOAD_DIR / temp_filename

    try:
        with open(temp_path, "wb") as f:
            f.write(content)

        # Send via AppleScript
        result = send_imessage_with_file(recipient, str(temp_path), message)

        if not result.success:
            status_code, error_type, user_message = _classify_send_error(result.error)
            logger.warning("Send with attachment failed: %s (type=%s)", user_message, error_type)
            raise HTTPException(
                status_code=status_code,
                detail={
                    "error": user_message,
                    "error_type": error_type,
                    "detail": result.error if result.error != user_message else None,
                },
            )

        logger.info("Attachment sent successfully to %s", recipient)
        _send_timestamps.append(time.time())
        return SendResponse(success=True)

    finally:
        # Clean up temp file after a delay (to allow Messages to process it)
        # We don't delete immediately because Messages.app may still be reading the file
        # The periodic cleanup will handle it eventually
        pass


class PollResponse(BaseModel):
    """Response from polling for new messages."""

    messages: list[MessageResponse]
    last_rowid: int  # Use this as after_rowid in next poll
    has_more: bool = False  # True if more messages available beyond limit


@app.get("/poll", response_model=PollResponse)
def poll_messages(
    after_rowid: int = Query(default=0, description="Return messages with ROWID > this value"),
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    limit: int = Query(default=100, le=500, description="Max messages to return"),
) -> PollResponse:
    """
    Poll for new messages since last_rowid.

    This is the primary endpoint for clients to check for new messages.
    Pass after_rowid=0 on first call to get initial messages, then use the
    returned last_rowid for subsequent polls.

    Example polling loop:
    1. GET /poll?after_rowid=0 -> returns messages, last_rowid=12345
    2. GET /poll?after_rowid=12345 -> returns new messages since 12345
    3. Repeat step 2 every N seconds

    Messages are returned in ascending order (oldest first) for easier
    processing of new messages.
    """
    # Fetch limit+1 to detect if there are more
    messages = get_messages(chat_id=chat_id, limit=limit + 1, after_rowid=after_rowid)

    # Messages come back newest-first, reverse for polling (oldest-first)
    messages.reverse()

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    # Determine last_rowid for next poll
    if messages:
        last_rowid = messages[-1].rowid
    else:
        last_rowid = after_rowid

    return PollResponse(
        messages=[_message_to_response(m) for m in messages],
        last_rowid=last_rowid,
        has_more=has_more,
    )


def _expand_tilde(path: str) -> Path:
    """Expand ~ in path to user's home directory."""
    if path.startswith("~/"):
        return Path.home() / path[2:]
    return Path(path)


# MIME type mappings for common iMessage attachment types
UTI_TO_MIME = {
    "public.heic": "image/heic",
    "public.jpeg": "image/jpeg",
    "public.png": "image/png",
    "public.gif": "image/gif",
    "public.tiff": "image/tiff",
    "com.compuserve.gif": "image/gif",
    "public.mpeg-4": "video/mp4",
    "com.apple.quicktime-movie": "video/quicktime",
    "public.mp3": "audio/mpeg",
    "public.mpeg-4-audio": "audio/mp4",
    "com.apple.m4a-audio": "audio/mp4",
    "public.pdf": "application/pdf",
}


def _is_heic(mime_type: str | None, uti: str | None, filename: str | None) -> bool:
    """Check if file is HEIC format."""
    if mime_type and "heic" in mime_type.lower():
        return True
    if uti and "heic" in uti.lower():
        return True
    if filename and filename.lower().endswith((".heic", ".heif")):
        return True
    return False


def _convert_heic_to_webp(file_path: Path) -> io.BytesIO:
    """Convert HEIC image to WebP format in memory."""
    with Image.open(file_path) as img:
        # Convert to RGB if necessary (HEIC might have alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        output = io.BytesIO()
        img.save(output, format="WEBP", quality=85)
        output.seek(0)
        return output


@app.get("/attachments/{attachment_id}", response_model=None)
def get_attachment_file(attachment_id: int) -> FileResponse | StreamingResponse:
    """
    Serve an attachment file.

    HEIC images are automatically converted to WebP for browser compatibility.
    """
    attachment = get_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if attachment.filename is None:
        raise HTTPException(status_code=404, detail="Attachment has no file")

    file_path = _expand_tilde(attachment.filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found on disk")

    # Determine MIME type
    mime_type = attachment.mime_type
    if mime_type is None and attachment.uti:
        mime_type = UTI_TO_MIME.get(attachment.uti)
    if mime_type is None:
        mime_type = "application/octet-stream"

    # Convert HEIC to WebP for browser compatibility
    if _is_heic(mime_type, attachment.uti, attachment.filename):
        try:
            webp_data = _convert_heic_to_webp(file_path)
            return StreamingResponse(
                webp_data,
                media_type="image/webp",
                headers={
                    "Content-Disposition": f'inline; filename="{file_path.stem}.webp"'
                },
            )
        except Exception as e:
            # Fall back to serving original if conversion fails
            pass

    return FileResponse(
        path=file_path,
        media_type=mime_type,
        filename=attachment.transfer_name or file_path.name,
    )


def _get_video_duration(file_path: Path) -> float | None:
    """Get video duration in seconds using ffprobe."""
    if not FFPROBE_AVAILABLE:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _get_cache_key(file_path: Path, suffix: str) -> str:
    """Generate a cache key based on file path and modification time."""
    stat = file_path.stat()
    key_data = f"{file_path}:{stat.st_mtime}:{stat.st_size}:{suffix}"
    return hashlib.md5(key_data.encode()).hexdigest()


def _is_cache_valid(cache_path: Path, ttl: int | None = None) -> bool:
    """Check if a cached file exists and is still valid."""
    if not cache_path.exists():
        return False
    if ttl is None:
        ttl = int(get_config_value("thumbnail_cache_ttl"))
    age = time.time() - cache_path.stat().st_mtime
    return age < ttl


def _extract_thumbnail(file_path: Path, timestamp: float | None = None) -> bytes | None:
    """Extract a thumbnail frame from video at given timestamp."""
    if not FFMPEG_AVAILABLE:
        return None

    if timestamp is None:
        timestamp = float(get_config_value("thumbnail_timestamp"))

    try:
        # Get duration to ensure we don't seek past end
        duration = _get_video_duration(file_path)
        if duration is not None and duration < timestamp:
            timestamp = min(duration / 2, 1.0)  # Use midpoint or 1s for short videos

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(timestamp),
                "-i", str(file_path),
                "-vframes", "1",
                "-f", "image2",
                "-c:v", "mjpeg",
                "-q:v", "3",  # Good quality JPEG
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except subprocess.TimeoutExpired:
        pass
    return None


def _is_quicktime_video(mime_type: str | None, uti: str | None) -> bool:
    """Check if file is a QuickTime/MOV video that needs transcoding."""
    if mime_type and mime_type.lower() in ("video/quicktime", "video/mov"):
        return True
    if uti and uti.lower() in ("com.apple.quicktime-movie", "public.movie"):
        return True
    return False


@app.get("/attachments/{attachment_id}/thumbnail", response_model=None)
def get_attachment_thumbnail(attachment_id: int) -> FileResponse | StreamingResponse:
    """
    Get a thumbnail image for a video attachment.

    Extracts a frame at 3 seconds (or earlier for short videos).
    Returns 404 if ffmpeg not available or extraction fails.
    """
    if not FFMPEG_AVAILABLE:
        raise HTTPException(status_code=404, detail="Thumbnails not available (ffmpeg not installed)")

    attachment = get_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if attachment.filename is None:
        raise HTTPException(status_code=404, detail="Attachment has no file")

    file_path = _expand_tilde(attachment.filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found on disk")

    # Check disk cache first (thumbnails are small, worth caching)
    cache_key = _get_cache_key(file_path, "thumb")
    cache_path = CACHE_DIR / f"{cache_key}.jpg"

    thumbnail_cache_ttl = int(get_config_value("thumbnail_cache_ttl"))
    if _is_cache_valid(cache_path, ttl=thumbnail_cache_ttl):
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={"Cache-Control": f"public, max-age={thumbnail_cache_ttl}"},
        )

    # Extract thumbnail
    thumbnail_data = _extract_thumbnail(file_path)
    if thumbnail_data is None:
        raise HTTPException(status_code=404, detail="Failed to extract thumbnail")

    # Save to disk cache (only if enough disk space)
    if _check_disk_space(len(thumbnail_data), CACHE_DIR):
        cache_path.write_bytes(thumbnail_data)

    return StreamingResponse(
        io.BytesIO(thumbnail_data),
        media_type="image/jpeg",
        headers={"Cache-Control": f"public, max-age={thumbnail_cache_ttl}"},
    )


from typing import Iterator


def _transcode_to_mp4_stream(input_path: Path) -> Iterator[bytes]:
    """
    Generator that yields MP4 chunks as ffmpeg produces them.

    Uses fragmented MP4 (fMP4) format which allows playback to start
    before the entire file is transcoded.
    """
    if not FFMPEG_AVAILABLE:
        return

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "frag_keyframe+empty_moov+faststart",  # Fragmented MP4 for streaming
            "-f", "mp4",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    try:
        # Read and yield chunks as they become available
        chunk_size = 64 * 1024  # 64KB chunks
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@app.get("/attachments/{attachment_id}/stream", response_model=None)
def stream_attachment(attachment_id: int) -> FileResponse | StreamingResponse:
    """
    Stream a transcoded version of a video attachment.

    MOV/QuickTime videos are transcoded to MP4 for browser playback.
    Uses chunked transfer encoding so playback can start immediately
    while transcoding continues in the background.
    Returns 404 if ffmpeg not available.
    """
    if not FFMPEG_AVAILABLE:
        raise HTTPException(status_code=404, detail="Streaming not available (ffmpeg not installed)")

    attachment = get_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if attachment.filename is None:
        raise HTTPException(status_code=404, detail="Attachment has no file")

    file_path = _expand_tilde(attachment.filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found on disk")

    # If already MP4, serve directly with cache headers
    mime_type = attachment.mime_type or ""
    if mime_type.lower() == "video/mp4":
        return FileResponse(
            file_path,
            media_type="video/mp4",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Stream transcoded MP4 chunks as they're produced
    return StreamingResponse(
        _transcode_to_mp4_stream(file_path),
        media_type="video/mp4",
        # Don't cache transcoded streams - they may be incomplete if interrupted
    )


from typing import Any


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint with database access status."""
    db_ok = check_db_access()
    return {
        "status": "ok" if db_ok else "degraded",
        "database_accessible": db_ok,
        "ffmpeg_available": FFMPEG_AVAILABLE,
        "ffprobe_available": FFPROBE_AVAILABLE,
        "contacts_available": contacts_available(),
    }


@app.get("/contacts/{handle}", response_model=ContactResponse)
def get_contact(handle: str) -> JSONResponse:
    """
    Look up contact information for a phone number or email.

    Returns contact name, initials, and whether they have a photo.
    Cache-Control header uses configured contact_cache_ttl.
    """
    logger.info("Looking up contact: %s", handle)
    if not contacts_available():
        logger.warning("Contact lookup not available")
        raise HTTPException(status_code=503, detail="Contact lookup not available")

    contact = resolve_contact(handle)
    logger.info("Resolved contact %s -> %s", handle, contact.name or "(no match)")
    response_data = _contact_to_response(contact)

    # Use configured cache TTL
    cache_ttl = get_config_value("contact_cache_ttl")
    return JSONResponse(
        content=response_data.model_dump(),
        headers={"Cache-Control": f"public, max-age={cache_ttl}"},
    )


@app.get("/contacts/{handle}/image")
def get_contact_image(handle: str) -> StreamingResponse:
    """
    Get the contact photo for a phone number or email.

    Returns the image as JPEG or the original format from Contacts.
    Cache-Control header uses configured contact_cache_ttl.
    """
    if not contacts_available():
        raise HTTPException(status_code=503, detail="Contact lookup not available")

    contact = resolve_contact(handle)
    if not contact.has_image or not contact.image_base64:
        raise HTTPException(status_code=404, detail="Contact has no image")

    import base64
    image_data = base64.b64decode(contact.image_base64)

    # Use configured cache TTL
    cache_ttl = get_config_value("contact_cache_ttl")
    return StreamingResponse(
        io.BytesIO(image_data),
        media_type="image/jpeg",
        headers={"Cache-Control": f"public, max-age={cache_ttl}"},
    )


# Configuration endpoints
class ConfigResponse(BaseModel):
    """Configuration response."""

    custom_css: str = ""
    prevent_sleep: bool = True
    sleep_mode: str = "ac_power"  # "ac_power" or "always"
    api_token: str = ""
    contact_cache_ttl: int = 86400  # seconds
    log_level: str = "WARNING"
    notifications_enabled: bool = True
    notification_sound_enabled: bool = True
    use_custom_notification_sound: bool = False
    theme: str = "auto"  # "auto", "light", or "dark"
    thumbnail_cache_ttl: int = 86400
    thumbnail_timestamp: float = 3.0
    websocket_poll_interval: float = 1.0
    auto_update_enabled: bool = True
    update_check_interval: int = 86400


class ConfigUpdateRequest(BaseModel):
    """Request to update configuration."""

    custom_css: str | None = None
    prevent_sleep: bool | None = None
    sleep_mode: str | None = None
    api_token: str | None = None
    contact_cache_ttl: int | None = None
    log_level: str | None = None
    notifications_enabled: bool | None = None
    notification_sound_enabled: bool | None = None
    use_custom_notification_sound: bool | None = None
    theme: str | None = None
    thumbnail_cache_ttl: int | None = None
    thumbnail_timestamp: float | None = None
    websocket_poll_interval: float | None = None
    auto_update_enabled: bool | None = None
    update_check_interval: int | None = None


@app.get("/config", response_model=ConfigResponse)
def get_configuration() -> ConfigResponse:
    """Get current configuration."""
    config = get_config()
    return ConfigResponse(**config)


@app.put("/config", response_model=ConfigResponse)
def update_configuration(request: ConfigUpdateRequest) -> ConfigResponse:
    """Update configuration values."""
    # Only update fields that were provided (not None)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if updates:
        config = update_config(updates)
        # Reconfigure logging if log_level changed
        if "log_level" in updates:
            from . import setup_logging
            setup_logging()
            logger.info("Log level changed to %s", updates["log_level"])
        # Start/stop caffeinate based on prevent_sleep setting
        if "prevent_sleep" in updates:
            if updates["prevent_sleep"]:
                start_caffeinate()
            else:
                stop_caffeinate()
        # Restart caffeinate if sleep_mode changed while prevent_sleep is enabled
        elif "sleep_mode" in updates:
            current_config = get_config()
            if current_config.get("prevent_sleep", False):
                stop_caffeinate()
                start_caffeinate(updates["sleep_mode"])
    else:
        config = get_config()
    return ConfigResponse(**config)


@app.get("/config/defaults", response_model=ConfigResponse)
def get_config_defaults() -> ConfigResponse:
    """Get default configuration values."""
    return ConfigResponse(**CONFIG_DEFAULTS)


# Sleep control endpoints


class SleepStatusResponse(BaseModel):
    """Response for sleep status endpoint."""

    caffeinate_running: bool
    prevent_sleep_enabled: bool


@app.get("/sleep/status", response_model=SleepStatusResponse)
def get_sleep_status() -> SleepStatusResponse:
    """Get current sleep prevention status."""
    config = get_config()
    return SleepStatusResponse(
        caffeinate_running=is_caffeinate_running(),
        prevent_sleep_enabled=config.get("prevent_sleep", False),
    )


@app.post("/sleep/allow", response_model=SleepStatusResponse)
def allow_sleep_now() -> SleepStatusResponse:
    """Temporarily allow system to sleep by stopping caffeinate.

    This does NOT change the prevent_sleep config setting.
    Caffeinate will restart on next server restart if prevent_sleep is enabled.
    """
    stop_caffeinate()
    config = get_config()
    return SleepStatusResponse(
        caffeinate_running=is_caffeinate_running(),
        prevent_sleep_enabled=config.get("prevent_sleep", False),
    )


@app.post("/sleep/prevent", response_model=SleepStatusResponse)
def prevent_sleep_now() -> SleepStatusResponse:
    """Re-engage sleep prevention by starting caffeinate.

    This does NOT change the prevent_sleep config setting.
    Use this to manually restart caffeinate after temporarily allowing sleep.
    """
    start_caffeinate()
    config = get_config()
    return SleepStatusResponse(
        caffeinate_running=is_caffeinate_running(),
        prevent_sleep_enabled=config.get("prevent_sleep", False),
    )


# Service management endpoints

from . import service as service_api_module


class ServiceStatusResponse(BaseModel):
    """Response for service status endpoint."""

    installed: bool
    loaded: bool
    running: bool
    pid: int | None
    plist_path: str | None
    stdout_log: str | None = None
    stderr_log: str | None = None
    tailscale_available: bool
    tailscale_connected: bool
    tailscale_serving: bool
    tailscale_serve_port: int | None = None
    tailscale_dns_name: str | None = None
    tailscale_url: str | None = None


@app.get("/service/status", response_model=ServiceStatusResponse)
def get_service_status() -> ServiceStatusResponse:
    """Get current service and Tailscale status."""
    status = service_api_module.get_status()
    return ServiceStatusResponse(**status)


class ServiceActionResponse(BaseModel):
    """Response for service install/uninstall actions."""

    success: bool
    message: str


@app.post("/service/install", response_model=ServiceActionResponse)
def install_service(
    host: str = Query(default="127.0.0.1", description="Host to bind to"),
    port: int = Query(default=1960, description="Port to bind to"),
    tailscale: bool = Query(default=False, description="Enable Tailscale serve"),
) -> ServiceActionResponse:
    """Install and start the LaunchAgent service.

    If tailscale=true, Tailscale serve will be configured to start/stop
    with the iuselinux service, tying their lifecycles together.
    """
    # Configure Tailscale before installing (so the service picks up the config)
    if tailscale:
        if not service_api_module.is_tailscale_available():
            return ServiceActionResponse(
                success=False,
                message="Tailscale CLI not found. Install Tailscale from https://tailscale.com/download"
            )
        if not service_api_module.is_tailscale_connected():
            return ServiceActionResponse(
                success=False,
                message="Tailscale is not connected. Run 'tailscale up' to connect."
            )
        # Save config - the serve command will enable Tailscale on startup
        update_config({
            "tailscale_serve_enabled": True,
            "tailscale_serve_port": port,
        })

    success, message = service_api_module.install(host=host, port=port, force=True)

    if success and tailscale:
        message += "\n\nTailscale serve is managed by the iuselinux service."

    return ServiceActionResponse(success=success, message=message)


@app.post("/service/uninstall", response_model=ServiceActionResponse)
def uninstall_service() -> ServiceActionResponse:
    """Stop and uninstall the LaunchAgent service."""
    success, message = service_api_module.uninstall()
    return ServiceActionResponse(success=success, message=message)


@app.post("/service/tailscale/enable", response_model=ServiceActionResponse)
def enable_tailscale(
    port: int = Query(default=1960, description="Port to serve"),
) -> ServiceActionResponse:
    """Enable Tailscale serve for remote access.

    This enables Tailscale serve immediately and saves the config so it
    will be re-enabled on service restart.
    """
    success, message = service_api_module.enable_tailscale_serve(port=port)
    if success:
        # Save config so it persists across restarts
        update_config({
            "tailscale_serve_enabled": True,
            "tailscale_serve_port": port,
        })
    return ServiceActionResponse(success=success, message=message)


@app.post("/service/tailscale/disable", response_model=ServiceActionResponse)
def disable_tailscale() -> ServiceActionResponse:
    """Disable Tailscale serve.

    This disables Tailscale serve immediately and clears the config so it
    won't be re-enabled on service restart.
    """
    success, message = service_api_module.disable_tailscale_serve()
    if success:
        # Clear config so it doesn't re-enable on restart
        update_config({
            "tailscale_serve_enabled": False,
        })
    return ServiceActionResponse(success=success, message=message)


class TrayStatusResponse(BaseModel):
    """Response for tray status."""

    installed: bool
    loaded: bool
    running: bool
    pid: int | None = None


@app.get("/tray/status", response_model=TrayStatusResponse)
def get_tray_status() -> TrayStatusResponse:
    """Get current tray status."""
    status = service_api_module.get_tray_status()
    return TrayStatusResponse(
        installed=bool(status.get("installed")),
        loaded=bool(status.get("loaded")),
        running=bool(status.get("running")),
        pid=status.get("pid") if status.get("pid") else None,
    )


@app.post("/tray/restart", response_model=ServiceActionResponse)
def restart_tray() -> ServiceActionResponse:
    """Restart the tray application.

    Unloads and reloads the tray LaunchAgent.
    """
    if not service_api_module.is_tray_installed():
        return ServiceActionResponse(
            success=False,
            message="Tray is not installed. Install the service first.",
        )

    plist_path = service_api_module.get_tray_plist_path()

    # Unload if currently loaded
    if service_api_module.is_tray_loaded():
        import subprocess

        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

    # Load the tray
    import subprocess

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return ServiceActionResponse(
            success=False,
            message=f"Failed to start tray: {result.stderr}",
        )

    return ServiceActionResponse(success=True, message="Tray restarted.")


# Version and update endpoints

from . import updater as updater_module


class VersionResponse(BaseModel):
    """Version information response."""

    current_version: str
    latest_version: str | None
    update_available: bool
    change_type: str | None = None  # 'major', 'minor', 'patch' for semver
    last_check: str | None
    error: str | None = None
    banner_dismissed: bool = False  # True if user has dismissed the banner
    update_command: str = "uv tool upgrade iuselinux"  # Command to run for update


class BannerDismissResponse(BaseModel):
    """Response from dismissing update banner."""

    success: bool
    dismissed_until: str | None  # ISO timestamp when dismissal expires


@app.get("/version", response_model=VersionResponse)
def get_version_info() -> VersionResponse:
    """Get current version and check for updates."""
    status = updater_module.get_update_status()

    # Check if banner was dismissed and if dismissal has expired
    dismissed_until = get_config_value("update_banner_dismissed_until")
    banner_dismissed = False
    if dismissed_until:
        from datetime import datetime, timezone

        try:
            expiry = datetime.fromisoformat(dismissed_until)
            if datetime.now(timezone.utc) < expiry:
                banner_dismissed = True
        except (ValueError, TypeError):
            pass

    return VersionResponse(
        **status,
        banner_dismissed=banner_dismissed,
        update_command="uv tool upgrade iuselinux",
    )


@app.post("/version/check", response_model=VersionResponse)
def check_for_updates() -> VersionResponse:
    """Force check for updates."""
    status = updater_module.get_update_status(force_check=True)

    # Check if banner was dismissed
    dismissed_until = get_config_value("update_banner_dismissed_until")
    banner_dismissed = False
    if dismissed_until:
        from datetime import datetime, timezone

        try:
            expiry = datetime.fromisoformat(dismissed_until)
            if datetime.now(timezone.utc) < expiry:
                banner_dismissed = True
        except (ValueError, TypeError):
            pass

    return VersionResponse(
        **status,
        banner_dismissed=banner_dismissed,
        update_command="uv tool upgrade iuselinux",
    )


@app.post("/version/dismiss-banner", response_model=BannerDismissResponse)
def dismiss_update_banner() -> BannerDismissResponse:
    """Dismiss the update banner for 48 hours.

    Only works for minor/patch updates. Major updates cannot be dismissed.
    """
    from datetime import datetime, timedelta, timezone

    status = updater_module.get_update_status()

    # Don't allow dismissing major updates
    if status.get("change_type") == "major":
        return BannerDismissResponse(
            success=False,
            dismissed_until=None,
        )

    # Set dismissal for 48 hours
    dismissed_until = datetime.now(timezone.utc) + timedelta(hours=48)
    set_config_value("update_banner_dismissed_until", dismissed_until.isoformat())

    return BannerDismissResponse(
        success=True,
        dismissed_until=dismissed_until.isoformat(),
    )


# WebSocket for real-time updates
MAX_WEBSOCKET_CONNECTIONS = 10
_active_websockets: set[WebSocket] = set()


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    token: str | None = Query(default=None, description="API token for authentication"),
) -> None:
    """
    WebSocket endpoint for real-time message updates.

    Connect to /ws or /ws?chat_id=N to receive new messages as they arrive.
    If API authentication is enabled, include ?token=YOUR_TOKEN.

    Messages sent to client:
    - {"type": "messages", "data": [...], "last_rowid": N} - new messages
    - {"type": "ping"} - keepalive ping every 30s

    Client can send:
    - {"type": "set_after_rowid", "rowid": N} - set the starting rowid
    """
    # Check connection limit to prevent DoS
    if len(_active_websockets) >= MAX_WEBSOCKET_CONNECTIONS:
        await websocket.close(code=1008, reason="Too many connections")
        logger.warning("WebSocket rejected: too many connections (%d)", len(_active_websockets))
        return

    # Check authentication if enabled
    api_token = get_config_value("api_token")
    if api_token and token != api_token:
        await websocket.close(code=4001, reason="API token required")
        return

    await websocket.accept()
    _active_websockets.add(websocket)
    logger.info("WebSocket connected (chat_id=%s, total=%d)", chat_id, len(_active_websockets))

    # Get poll interval from config
    poll_interval = float(get_config_value("websocket_poll_interval"))

    # Start with the latest rowid (don't send historical messages)
    try:
        messages = get_messages(chat_id=chat_id, limit=1)
        last_rowid = messages[0].rowid if messages else 0
    except Exception as e:
        logger.error("WebSocket init failed: %s", e)
        await websocket.send_json({"type": "error", "message": str(e)})
        _active_websockets.discard(websocket)
        await websocket.close()
        return

    ping_counter = 0

    try:
        while True:
            # Check for new messages
            try:
                new_messages = get_messages(
                    chat_id=chat_id,
                    limit=100,
                    after_rowid=last_rowid,
                )
            except Exception as e:
                logger.error("WebSocket poll error: %s", e)
                await websocket.send_json({"type": "error", "message": str(e)})
                await asyncio.sleep(poll_interval)
                continue

            if new_messages:
                # Sort oldest first for client processing
                new_messages.sort(key=lambda m: m.rowid)
                last_rowid = new_messages[-1].rowid
                logger.info("WebSocket pushing %d new messages", len(new_messages))

                await websocket.send_json({
                    "type": "messages",
                    "data": [_message_to_response(m).model_dump() for m in new_messages],
                    "last_rowid": last_rowid,
                })

            # Send ping every ~30 seconds to keep connection alive
            ping_counter += 1
            if ping_counter >= 30:
                await websocket.send_json({"type": "ping"})
                ping_counter = 0

            # Check for client messages (non-blocking)
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=poll_interval,
                )
                # Handle client commands
                if data.get("type") == "set_after_rowid":
                    last_rowid = data.get("rowid", last_rowid)
                    logger.info("WebSocket set after_rowid=%d", last_rowid)
            except asyncio.TimeoutError:
                # No message from client, continue polling
                pass

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (chat_id=%s)", chat_id)
    except Exception as e:
        logger.error("WebSocket unexpected error: %s", e)
    finally:
        _active_websockets.discard(websocket)


import signal
import sys
from types import FrameType

import click

from . import service as service_module


class DefaultGroup(click.Group):
    """A click Group that invokes a default command if no subcommand is given."""

    def __init__(self, *args, default_cmd: str | None = None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # If no args or first arg looks like an option, invoke default command
        if not args or args[0].startswith("-"):
            if self.default_cmd:
                args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)


@click.group(cls=DefaultGroup, default_cmd="serve", invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """iuselinux - Remote iMessage gateway for macOS."""
    pass


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=1960, help="Port to bind to")
@click.option(
    "--api-token",
    default=None,
    help="Set API token for authentication. If provided, overwrites any existing token.",
)
def serve(host: str, port: int, api_token: str | None) -> None:
    """Run the iuselinux server (default command)."""
    import uvicorn

    # Check for conflicts (service already running, port in use)
    can_start, conflict_msg = service_module.check_startup_conflicts(host=host, port=port)
    if not can_start:
        click.echo(click.style("Cannot start server:", fg="yellow"))
        click.echo(conflict_msg)
        sys.exit(0)  # Exit gracefully, not an error

    # Check database access at startup and report any issues
    _check_and_report_db_access()

    # Set API token if provided via CLI
    if api_token is not None:
        set_config_value("api_token", api_token)
        print(f"API token set (length: {len(api_token)} chars)")

    # Start caffeinate if enabled in config
    config = get_config()
    if config.get("prevent_sleep", False):
        if start_caffeinate():
            print("Caffeinate started - preventing system sleep")

    # Track whether we started Tailscale serve (so we know to clean it up)
    tailscale_started = False

    # Enable Tailscale serve if configured
    if config.get("tailscale_serve_enabled", False):
        ts_port = config.get("tailscale_serve_port", port)
        # Use the server port if config port doesn't match (user may have changed --port)
        if ts_port != port:
            ts_port = port
        ts_success, ts_message = service_module.enable_tailscale_serve(port=ts_port)
        if ts_success:
            print(f"Tailscale serve enabled on port {ts_port}")
            tailscale_started = True
        else:
            print(f"Warning: Could not enable Tailscale serve: {ts_message}")

    def cleanup(signum: int | None = None, frame: FrameType | None = None) -> None:
        """Clean up caffeinate and Tailscale on exit."""
        stop_caffeinate()
        # Disable Tailscale serve if we started it
        if tailscale_started:
            service_module.disable_tailscale_serve()
        sys.exit(0)

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        stop_caffeinate()
        # Also disable Tailscale serve on normal exit
        if tailscale_started:
            service_module.disable_tailscale_serve()


@main.group()
def service() -> None:
    """Manage the iuselinux LaunchAgent service."""
    pass


@service.command("install")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=1960, help="Port to bind to")
@click.option("--force", is_flag=True, help="Overwrite existing installation")
@click.option("--tailscale", is_flag=True, help="Enable Tailscale serve for remote access")
@click.option("--no-tray", is_flag=True, help="Skip installing the menu bar tray icon")
def service_install(host: str, port: int, force: bool, tailscale: bool, no_tray: bool) -> None:
    """Install and start the LaunchAgent service.

    The service will automatically start on login and restart on failure.
    If --tailscale is provided, Tailscale serve will be enabled when the
    server starts and disabled when it stops. This ties the Tailscale
    lifecycle to the iuselinux service.

    By default, a menu bar tray icon is also installed. Use --no-tray to
    skip the tray icon installation.
    """
    # Configure Tailscale before installing (so the service picks up the config)
    if tailscale:
        # Validate Tailscale is available before proceeding
        if not service_module.is_tailscale_available():
            click.echo(click.style(
                "Error: Tailscale CLI not found. Install Tailscale from https://tailscale.com/download",
                fg="red"
            ), err=True)
            sys.exit(1)
        if not service_module.is_tailscale_connected():
            click.echo(click.style(
                "Error: Tailscale is not connected. Run 'tailscale up' to connect.",
                fg="red"
            ), err=True)
            sys.exit(1)

        # Save Tailscale config - the serve command will enable it on startup
        update_config({
            "tailscale_serve_enabled": True,
            "tailscale_serve_port": port,
        })
        click.echo("Tailscale serve configured (will start with service)")

    success, message = service_module.install(
        host=host, port=port, force=force, tray=not no_tray
    )
    if success:
        click.echo(click.style(message, fg="green"))
        click.echo(f"\nServer will be available at http://{host}:{port}")

        if tailscale:
            click.echo("\nTailscale serve is managed by the iuselinux service:")
            click.echo("  - Enabled when service starts")
            click.echo("  - Disabled when service stops")
            ts_url = service_module.get_tailscale_url()
            if ts_url:
                click.echo(f"  - Access via {ts_url}")
            else:
                click.echo("  - Access via https://your-machine.tailnet-name.ts.net")
    else:
        click.echo(click.style(f"Error: {message}", fg="red"), err=True)
        sys.exit(1)


@service.command("uninstall")
def service_uninstall() -> None:
    """Stop and uninstall the LaunchAgent service."""
    success, message = service_module.uninstall()
    if success:
        click.echo(click.style(message, fg="green"))
    else:
        click.echo(click.style(f"Error: {message}", fg="red"), err=True)
        sys.exit(1)


@service.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def service_status(as_json: bool) -> None:
    """Show the status of the LaunchAgent service."""
    status = service_module.get_status()

    if as_json:
        import json
        click.echo(json.dumps(status, indent=2))
    else:
        click.echo(service_module.format_status(status))


# Tray commands


@main.group()
def tray() -> None:
    """Manage the iuselinux menu bar tray icon."""
    pass


@tray.command("run")
def tray_run() -> None:
    """Run the tray application directly (used by LaunchAgent)."""
    from .tray import run_tray
    run_tray()


@tray.command("start")
def tray_start() -> None:
    """Start the menu bar tray icon."""
    if not service_module.is_tray_installed():
        click.echo(click.style("Tray is not installed.", fg="yellow"))
        click.echo("Run 'iuselinux service install' to install both server and tray.")
        sys.exit(1)

    if service_module.is_tray_loaded():
        click.echo("Tray is already running.")
        return

    tray_plist = service_module.get_tray_plist_path()
    result = subprocess.run(
        ["launchctl", "load", str(tray_plist)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo(click.style("Tray started.", fg="green"))
    else:
        click.echo(click.style(f"Failed to start tray: {result.stderr}", fg="red"), err=True)
        sys.exit(1)


@tray.command("stop")
def tray_stop() -> None:
    """Stop the menu bar tray icon."""
    if not service_module.is_tray_loaded():
        click.echo("Tray is not running.")
        return

    tray_plist = service_module.get_tray_plist_path()
    result = subprocess.run(
        ["launchctl", "unload", str(tray_plist)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo(click.style("Tray stopped.", fg="green"))
    else:
        click.echo(click.style(f"Failed to stop tray: {result.stderr}", fg="red"), err=True)
        sys.exit(1)


@tray.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def tray_status(as_json: bool) -> None:
    """Show the status of the menu bar tray icon."""
    status = service_module.get_tray_status()

    if as_json:
        import json
        click.echo(json.dumps(status, indent=2))
    else:
        if not status["installed"]:
            click.echo("Tray: not installed")
            click.echo("  Run 'iuselinux service install' to install both server and tray.")
        elif status["running"]:
            click.echo(f"Tray: running (PID {status.get('pid', 'unknown')})")
        elif status["loaded"]:
            click.echo("Tray: loaded but not running")
        else:
            click.echo("Tray: installed but not loaded")
            click.echo("  Run 'iuselinux tray start' to start the tray.")


if __name__ == "__main__":
    main()
