"""FastAPI server for iMessage Gateway."""

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path

import asyncio

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
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
CACHE_DIR = Path(tempfile.gettempdir()) / "imessage_gateway_cache"
CACHE_DIR.mkdir(exist_ok=True)
THUMBNAIL_CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds


# Rate limiting for send endpoint
RATE_LIMIT_MESSAGES = 10  # Max messages per window
RATE_LIMIT_WINDOW = 60  # Window in seconds
_send_timestamps: deque[float] = deque()

from .db import FullDiskAccessError, check_db_access
from .messages import get_chats, get_messages, get_attachment, Chat, Message, Attachment
from .sender import send_imessage, SendResult

app = FastAPI(
    title="iMessage Gateway",
    description="Read and send iMessages via local API",
    version="0.1.0",
)

# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(FullDiskAccessError)
async def full_disk_access_handler(request: Request, exc: FullDiskAccessError):
    """Handle missing Full Disk Access permission."""
    return JSONResponse(
        status_code=403,
        content={
            "detail": str(exc),
            "error_type": "full_disk_access_required",
        },
    )


@app.get("/")
def index():
    """Serve the main UI."""
    return FileResponse(static_dir / "index.html")


# Response models
class ChatResponse(BaseModel):
    """Chat/conversation response."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None
    last_message_time: str | None  # ISO format
    participants: list[str] | None = None  # For group chats


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
        raise ValueError("recipient must be a valid phone number or email")

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


def _chat_to_response(chat: Chat) -> ChatResponse:
    """Convert Chat dataclass to response model."""
    return ChatResponse(
        rowid=chat.rowid,
        guid=chat.guid,
        display_name=chat.display_name,
        identifier=chat.identifier,
        last_message_time=chat.last_message_time.isoformat() if chat.last_message_time else None,
        participants=chat.participants,
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
    )


@app.get("/chats", response_model=list[ChatResponse])
def list_chats(limit: int = Query(default=100, le=500)) -> list[ChatResponse]:
    """List all chats/conversations."""
    chats = get_chats(limit=limit)
    return [_chat_to_response(c) for c in chats]


@app.get("/messages", response_model=list[MessageResponse])
def list_messages(
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    limit: int = Query(default=50, le=500),
    after_rowid: int | None = Query(default=None, description="Only messages after this rowid"),
) -> list[MessageResponse]:
    """Fetch messages, optionally filtered by chat."""
    messages = get_messages(chat_id=chat_id, limit=limit, after_rowid=after_rowid)
    return [_message_to_response(m) for m in messages]


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
    _check_rate_limit()

    result = send_imessage(request.recipient, request.message)
    if not result.success:
        status_code, error_type, user_message = _classify_send_error(result.error)
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": user_message,
                "error_type": error_type,
                "detail": result.error if result.error != user_message else None,
            },
        )

    _send_timestamps.append(time.time())
    return SendResponse(success=True)


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


@app.get("/attachments/{attachment_id}")
def get_attachment_file(attachment_id: int):
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


def _is_cache_valid(cache_path: Path, ttl: int = THUMBNAIL_CACHE_TTL) -> bool:
    """Check if a cached file exists and is still valid."""
    if not cache_path.exists():
        return False
    age = time.time() - cache_path.stat().st_mtime
    return age < ttl


def _extract_thumbnail(file_path: Path, timestamp: float = 3.0) -> bytes | None:
    """Extract a thumbnail frame from video at given timestamp."""
    if not FFMPEG_AVAILABLE:
        return None

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


@app.get("/attachments/{attachment_id}/thumbnail")
def get_attachment_thumbnail(attachment_id: int):
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

    if _is_cache_valid(cache_path, ttl=THUMBNAIL_CACHE_TTL):
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},  # 24h browser cache
        )

    # Extract thumbnail
    thumbnail_data = _extract_thumbnail(file_path)
    if thumbnail_data is None:
        raise HTTPException(status_code=404, detail="Failed to extract thumbnail")

    # Save to disk cache
    cache_path.write_bytes(thumbnail_data)

    return StreamingResponse(
        io.BytesIO(thumbnail_data),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _transcode_to_mp4_bytes(input_path: Path) -> bytes | None:
    """Transcode video to MP4 format in memory for streaming."""
    if not FFMPEG_AVAILABLE:
        return None

    try:
        # Transcode to stdout with fragmented MP4 for streaming
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "frag_keyframe+empty_moov",  # Fragmented MP4 for streaming
                "-f", "mp4",
                "pipe:1",
            ],
            capture_output=True,
            timeout=300,  # 5 minute timeout for long videos
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except subprocess.TimeoutExpired:
        pass
    return None


@app.get("/attachments/{attachment_id}/stream")
def stream_attachment(attachment_id: int):
    """
    Stream a transcoded version of a video attachment.

    MOV/QuickTime videos are transcoded to MP4 for browser playback.
    Browser should cache response for 24 hours via Cache-Control header.
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

    # Transcode to MP4 and stream (browser caches via Cache-Control)
    mp4_data = _transcode_to_mp4_bytes(file_path)
    if mp4_data is None:
        raise HTTPException(status_code=500, detail="Failed to transcode video")

    return StreamingResponse(
        io.BytesIO(mp4_data),
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=86400"},  # 24h browser cache
    )


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint with database access status."""
    db_ok = check_db_access()
    return {
        "status": "ok" if db_ok else "degraded",
        "database_accessible": db_ok,
        "ffmpeg_available": FFMPEG_AVAILABLE,
        "ffprobe_available": FFPROBE_AVAILABLE,
    }


# WebSocket for real-time updates
WEBSOCKET_POLL_INTERVAL = 1.0  # seconds between polls


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
):
    """
    WebSocket endpoint for real-time message updates.

    Connect to /ws or /ws?chat_id=N to receive new messages as they arrive.

    Messages sent to client:
    - {"type": "messages", "data": [...], "last_rowid": N} - new messages
    - {"type": "ping"} - keepalive ping every 30s

    Client can send:
    - {"type": "set_after_rowid", "rowid": N} - set the starting rowid
    """
    await websocket.accept()

    # Start with the latest rowid (don't send historical messages)
    messages = get_messages(chat_id=chat_id, limit=1)
    last_rowid = messages[0].rowid if messages else 0

    ping_counter = 0

    try:
        while True:
            # Check for new messages
            new_messages = get_messages(
                chat_id=chat_id,
                limit=100,
                after_rowid=last_rowid,
            )

            if new_messages:
                # Sort oldest first for client processing
                new_messages.sort(key=lambda m: m.rowid)
                last_rowid = new_messages[-1].rowid

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
                    timeout=WEBSOCKET_POLL_INTERVAL,
                )
                # Handle client commands
                if data.get("type") == "set_after_rowid":
                    last_rowid = data.get("rowid", last_rowid)
            except asyncio.TimeoutError:
                # No message from client, continue polling
                pass

    except WebSocketDisconnect:
        pass
