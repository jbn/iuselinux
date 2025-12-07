"""Attachment widget for displaying message attachments."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from iuselinux.tui.image_renderer import get_renderer
from iuselinux.tui.terminal_graphics import get_terminal_capabilities

if TYPE_CHECKING:
    from iuselinux.tui.models import Attachment

logger = logging.getLogger(__name__)


class AttachmentWidget(Static):
    """Widget for displaying an attachment.

    For image attachments in terminals with graphics support,
    displays inline images. Otherwise shows a text placeholder.

    Press 'o' or Enter to open the attachment in an external app.
    """

    # Default dimensions for inline images (in terminal cells)
    DEFAULT_IMAGE_WIDTH = 40
    DEFAULT_IMAGE_HEIGHT = 15

    # Allow focus and add keybindings
    can_focus = True

    BINDINGS = [
        Binding("enter", "open_attachment", "Open", show=True),
        Binding("o", "open_attachment", "Open", show=False),
    ]

    def __init__(
        self,
        attachment: Attachment,
        max_width: int = DEFAULT_IMAGE_WIDTH,
        max_height: int = DEFAULT_IMAGE_HEIGHT,
    ) -> None:
        """Initialize the attachment widget.

        Args:
            attachment: The attachment to display
            max_width: Maximum width in terminal cells
            max_height: Maximum height in terminal cells
        """
        super().__init__(classes="attachment")
        self.attachment = attachment
        self.max_width = max_width
        self.max_height = max_height
        self._image_data: bytes | None = None
        self._load_error: str | None = None
        self._loading: bool = False
        self._opening: bool = False

    def compose_placeholder(self) -> Text:
        """Create a placeholder for the attachment."""
        att = self.attachment
        if att.is_image:
            icon = "[Image]"
            style = "cyan"
        elif att.is_video:
            icon = "[Video]"
            style = "magenta"
        else:
            icon = "[File]"
            style = "yellow"

        text = Text()
        text.append(icon, style=style)
        if att.filename:
            text.append(f" {att.filename}", style="dim")
        return text

    def on_mount(self) -> None:
        """Start loading attachment if image and graphics supported."""
        caps = get_terminal_capabilities()
        renderer = get_renderer(caps)

        if self.attachment.is_image and renderer is not None:
            # Terminal supports inline images - start loading
            self._loading = True
            self.update(Text("Loading image...", style="dim italic"))
            self.run_worker(self._load_and_render())
        else:
            # No graphics support - show placeholder
            self.update(self.compose_placeholder())

    async def _load_and_render(self) -> None:
        """Load attachment data and render as inline image."""
        from iuselinux.tui.app import IMessageApp

        app = self.app
        if not isinstance(app, IMessageApp):
            self._show_error("App not available")
            return

        try:
            # Try thumbnail first if available
            url = self.attachment.thumbnail_url or self.attachment.url
            self._image_data = await app.api.get_attachment(url)

            # Render the image
            caps = get_terminal_capabilities()
            renderer = get_renderer(caps)
            if renderer is None:
                self._show_placeholder()
                return

            escape_sequence = renderer.render_from_bytes(
                self._image_data,
                max_width=self.max_width,
                max_height=self.max_height,
            )

            # Update widget with the rendered image
            self._loading = False
            # Use Rich's Control to emit raw escape sequences
            self.update(InlineImage(escape_sequence, self.attachment.filename))

        except Exception as e:
            logger.error("Failed to load attachment: %s", e)
            self._show_error(str(e))

    def _show_error(self, error: str) -> None:
        """Show error state."""
        self._loading = False
        self._load_error = error
        text = self.compose_placeholder()
        text.append(f" (load failed)", style="red dim")
        self.update(text)

    def _show_placeholder(self) -> None:
        """Show placeholder text."""
        self._loading = False
        self.update(self.compose_placeholder())

    async def action_open_attachment(self) -> None:
        """Open the attachment in an external application."""
        if self._opening:
            return

        from iuselinux.tui.app import IMessageApp
        from iuselinux.tui.attachment_utils import (
            download_attachment_to_temp,
            open_file_with_system_app,
        )

        app = self.app
        if not isinstance(app, IMessageApp):
            self.notify("Cannot open attachment", severity="error")
            return

        self._opening = True
        filename = self.attachment.filename or "attachment"
        self.notify(f"Opening {filename}...")

        try:
            # Download to temp file
            file_path = await download_attachment_to_temp(
                self.attachment, app.api
            )

            if file_path is None:
                self.notify("Failed to download attachment", severity="error")
                return

            # Open with system app
            success = open_file_with_system_app(file_path)
            if not success:
                self.notify("Failed to open attachment", severity="error")

        except Exception as e:
            logger.error("Failed to open attachment: %s", e)
            self.notify(f"Error: {e}", severity="error")
        finally:
            self._opening = False


class InlineImage:
    """Rich renderable for inline terminal images.

    This wraps a terminal escape sequence to be rendered by Rich.
    """

    def __init__(self, escape_sequence: str, filename: str | None = None) -> None:
        """Initialize the inline image.

        Args:
            escape_sequence: The terminal escape sequence to render the image
            filename: Optional filename to show below the image
        """
        self.escape_sequence = escape_sequence
        self.filename = filename

    def __rich__(self) -> RenderableType:
        """Return rich representation."""
        # We need to emit raw escape sequences
        # Rich's Text with markup=False should pass through
        text = Text()
        text.append(self.escape_sequence)
        if self.filename:
            text.append(f"\n{self.filename}", style="dim italic")
        return text

    def __rich_console__(self, console, options):
        """Yield segments for Rich console rendering."""
        from rich.segment import Segment
        from rich.style import Style

        # Emit the raw escape sequence
        yield Segment(self.escape_sequence)
        if self.filename:
            yield Segment("\n")
            yield Segment(self.filename, Style(dim=True, italic=True))
