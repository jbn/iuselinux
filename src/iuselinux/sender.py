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

    Handles backslashes, quotes, and control characters that could
    break out of string context and allow command injection.
    """
    # Escape backslashes first (must be first to avoid double-escaping)
    s = s.replace("\\", "\\\\")
    # Escape double quotes
    s = s.replace('"', '\\"')
    # SECURITY FIX: Escape control characters to prevent command injection.
    # Without this, a message like 'Hello"\ntell app "Finder" to delete files'
    # could break out of the AppleScript string context and execute arbitrary code.
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


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


def send_imessage_with_file(recipient: str, file_path: str, message: str | None = None) -> SendResult:
    """
    Send an iMessage with a file attachment.

    Args:
        recipient: Phone number, email address, or full chat GUID (for group chats)
        file_path: Absolute path to the file to send
        message: Optional text message to send with the file

    Returns:
        SendResult with success status and any error message
    """
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return SendResult(success=False, error=f"File not found: {file_path}")

    if not path.is_absolute():
        return SendResult(success=False, error="File path must be absolute")

    logger.info("Sending iMessage with file to %s: %s", recipient, file_path)

    # Escape strings for AppleScript
    safe_path = _escape_applescript_string(file_path)

    # Build the AppleScript based on recipient type
    if _is_chat_guid(recipient):
        safe_chat_id = _escape_applescript_string(recipient)
        if message:
            safe_message = _escape_applescript_string(message)
            applescript = f'''
            tell application "Messages"
                set targetChat to chat id "{safe_chat_id}"
                send (POSIX file "{safe_path}") to targetChat
                send "{safe_message}" to targetChat
            end tell
            '''
        else:
            applescript = f'''
            tell application "Messages"
                set targetChat to chat id "{safe_chat_id}"
                send (POSIX file "{safe_path}") to targetChat
            end tell
            '''
    else:
        safe_recipient = _escape_applescript_string(recipient)
        if message:
            safe_message = _escape_applescript_string(message)
            applescript = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{safe_recipient}" of targetService
                send (POSIX file "{safe_path}") to targetBuddy
                send "{safe_message}" to targetBuddy
            end tell
            '''
        else:
            applescript = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{safe_recipient}" of targetService
                send (POSIX file "{safe_path}") to targetBuddy
            end tell
            '''

    try:
        logger.debug("Executing AppleScript for file send")
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=60,  # Longer timeout for file transfers
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.warning("AppleScript failed: %s", error_msg)
            return SendResult(success=False, error=error_msg)

        logger.info("File sent successfully to %s", recipient)
        return SendResult(success=True)

    except subprocess.TimeoutExpired:
        logger.error("AppleScript timeout sending file to %s", recipient)
        return SendResult(success=False, error="Timeout: Messages.app did not respond")
    except Exception as e:
        logger.error("AppleScript exception: %s", e)
        return SendResult(success=False, error=str(e))
