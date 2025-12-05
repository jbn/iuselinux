"""Send iMessages via AppleScript."""

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("iuselinux.sender")


@dataclass
class SendResult:
    """Result of sending a message."""

    success: bool
    error: str | None = None


def _escape_applescript_string(s: str) -> str:
    """
    Escape a string for safe inclusion in AppleScript.

    Handles quotes and backslashes.
    """
    # Escape backslashes first, then quotes
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _is_chat_guid(recipient: str) -> bool:
    """Check if recipient is a full chat GUID (group chat) rather than phone/email.

    Full chat GUIDs have format: iMessage;+;chat123456 or SMS;+;chat123456
    """
    import re
    return bool(re.match(r"^(iMessage|SMS|RCS);[+-];chat\d+$", recipient))


def send_imessage(recipient: str, message: str) -> SendResult:
    """
    Send an iMessage to a recipient.

    Args:
        recipient: Phone number, email address, or full chat GUID (for group chats)
        message: Text message to send

    Returns:
        SendResult with success status and any error message
    """
    logger.info("Sending iMessage to %s (length=%d)", recipient, len(message))

    # Escape the strings for AppleScript
    safe_message = _escape_applescript_string(message)

    # Different AppleScript for chat GUIDs vs phone/email
    if _is_chat_guid(recipient):
        # For group chats, send to the chat by its full GUID
        # Format: iMessage;+;chat123456 or SMS;+;chat123456 or RCS;+;chat123456
        safe_chat_id = _escape_applescript_string(recipient)
        applescript = f'''
        tell application "Messages"
            set targetChat to chat id "{safe_chat_id}"
            send "{safe_message}" to targetChat
        end tell
        '''
    else:
        # For 1:1 chats, send to the buddy (phone/email)
        safe_recipient = _escape_applescript_string(recipient)
        applescript = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{safe_recipient}" of targetService
            send "{safe_message}" to targetBuddy
        end tell
        '''

    try:
        logger.debug("Executing AppleScript for message send")
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.warning("AppleScript failed: %s", error_msg)
            return SendResult(success=False, error=error_msg)

        logger.info("Message sent successfully to %s", recipient)
        return SendResult(success=True)

    except subprocess.TimeoutExpired:
        logger.error("AppleScript timeout sending to %s", recipient)
        return SendResult(success=False, error="Timeout: Messages.app did not respond")
    except Exception as e:
        logger.error("AppleScript exception: %s", e)
        return SendResult(success=False, error=str(e))
