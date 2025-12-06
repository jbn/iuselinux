"""HTTP API client for the TUI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from iuselinux.tui.models import (
    Attachment,
    Chat,
    Contact,
    HealthStatus,
    Message,
    Participant,
    SearchResult,
)


class APIError(Exception):
    """Error from the API."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class ConnectionError(Exception):
    """Error connecting to the server."""

    pass


class APIClient:
    """Async HTTP client for the iMessage Gateway API."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the client."""
        self.base_url = f"http://{host}:{port}"
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an HTTP request and return JSON."""
        try:
            response = await self.client.request(method, path, **kwargs)
            if response.status_code >= 400:
                try:
                    error = response.json()
                    message = error.get("detail", response.text)
                except Exception:
                    message = response.text
                raise APIError(response.status_code, message)
            return response.json()
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot connect to {self.base_url}: {e}") from e
        except httpx.TimeoutException as e:
            raise ConnectionError(f"Request timed out: {e}") from e

    # Health check

    async def health(self) -> HealthStatus:
        """Check server health."""
        data = await self._request("GET", "/health")
        return HealthStatus(
            status=data.get("status", "unknown"),
            database=data.get("database", False),
            ffmpeg=data.get("ffmpeg", False),
            contacts=data.get("contacts", False),
        )

    # Chat operations

    async def get_chats(self, limit: int = 100) -> list[Chat]:
        """Get list of chats."""
        data = await self._request("GET", "/chats", params={"limit": limit})
        return [self._parse_chat(c) for c in data]

    # Message operations

    async def get_messages(
        self,
        chat_id: int,
        limit: int = 50,
        before_rowid: int | None = None,
        after_rowid: int | None = None,
    ) -> list[Message]:
        """Get messages for a chat."""
        params: dict[str, Any] = {"chat_id": chat_id, "limit": limit}
        if before_rowid is not None:
            params["before_rowid"] = before_rowid
        if after_rowid is not None:
            params["after_rowid"] = after_rowid
        data = await self._request("GET", "/messages", params=params)
        return [self._parse_message(m) for m in data]

    async def poll_messages(
        self,
        after_rowid: int,
        chat_id: int | None = None,
        limit: int = 100,
    ) -> tuple[list[Message], int]:
        """Poll for new messages. Returns (messages, latest_rowid)."""
        params: dict[str, Any] = {"after_rowid": after_rowid, "limit": limit}
        if chat_id is not None:
            params["chat_id"] = chat_id
        data = await self._request("GET", "/poll", params=params)
        messages = [self._parse_message(m) for m in data.get("messages", [])]
        latest = data.get("latest_rowid", after_rowid)
        return messages, latest

    async def send_message(self, recipient: str, message: str) -> bool:
        """Send a message. Returns True on success."""
        data = await self._request(
            "POST",
            "/send",
            json={"recipient": recipient, "message": message},
        )
        return data.get("success", False)

    # Search

    async def search(
        self,
        query: str,
        chat_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SearchResult], int]:
        """Search messages. Returns (results, total_count)."""
        params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
        if chat_id is not None:
            params["chat_id"] = chat_id
        data = await self._request("GET", "/search", params=params)
        results = []
        for item in data.get("results", []):
            msg = self._parse_message(item["message"])
            chat = self._parse_chat(item["chat"]) if item.get("chat") else None
            results.append(SearchResult(message=msg, chat=chat))
        return results, data.get("total", 0)

    # Config

    async def get_config(self) -> dict[str, Any]:
        """Get server configuration."""
        return await self._request("GET", "/config")

    async def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Update server configuration."""
        return await self._request("PUT", "/config", json=updates)

    # Parsing helpers

    def _parse_contact(self, data: dict[str, Any] | None) -> Contact | None:
        """Parse contact from API response."""
        if not data:
            return None
        return Contact(
            handle=data["handle"],
            name=data.get("name"),
            given_name=data.get("given_name"),
            family_name=data.get("family_name"),
            nickname=data.get("nickname"),
            initials=data.get("initials"),
            has_image=data.get("has_image", False),
            image_url=data.get("image_url"),
        )

    def _parse_participant(self, data: dict[str, Any]) -> Participant:
        """Parse participant from API response."""
        return Participant(
            handle=data["handle"],
            contact=self._parse_contact(data.get("contact")),
        )

    def _parse_attachment(self, data: dict[str, Any]) -> Attachment:
        """Parse attachment from API response."""
        return Attachment(
            rowid=data["rowid"],
            guid=data["guid"],
            mime_type=data.get("mime_type"),
            filename=data.get("filename"),
            total_bytes=data.get("total_bytes", 0),
            url=data["url"],
            thumbnail_url=data.get("thumbnail_url"),
            stream_url=data.get("stream_url"),
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse ISO datetime string."""
        if not value:
            return None
        try:
            # Handle both with and without timezone
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _parse_message(self, data: dict[str, Any]) -> Message:
        """Parse message from API response."""
        return Message(
            rowid=data["rowid"],
            guid=data["guid"],
            text=data.get("text"),
            timestamp=self._parse_datetime(data.get("timestamp")),
            is_from_me=data.get("is_from_me", False),
            handle_id=data.get("handle_id"),
            chat_id=data.get("chat_id"),
            tapback_type=data.get("tapback_type"),
            associated_guid=data.get("associated_guid"),
            attachments=[
                self._parse_attachment(a) for a in data.get("attachments", [])
            ],
            contact=self._parse_contact(data.get("contact")),
        )

    def _parse_chat(self, data: dict[str, Any]) -> Chat:
        """Parse chat from API response."""
        participant_contacts = None
        if data.get("participant_contacts"):
            participant_contacts = [
                self._parse_participant(p) for p in data["participant_contacts"]
            ]
        return Chat(
            rowid=data["rowid"],
            guid=data["guid"],
            display_name=data.get("display_name"),
            identifier=data.get("identifier"),
            last_message_time=self._parse_datetime(data.get("last_message_time")),
            last_message_text=data.get("last_message_text"),
            last_message_is_from_me=data.get("last_message_is_from_me", False),
            participants=data.get("participants"),
            participant_contacts=participant_contacts,
            contact=self._parse_contact(data.get("contact")),
        )
