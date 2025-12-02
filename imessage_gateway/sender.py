"""Send iMessages via AppleScript."""

import subprocess
from dataclasses import dataclass


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


def send_imessage(recipient: str, message: str) -> SendResult:
    """
    Send an iMessage to a recipient.

    Args:
        recipient: Phone number or email address
        message: Text message to send

    Returns:
        SendResult with success status and any error message
    """
    # Escape the strings for AppleScript
    safe_recipient = _escape_applescript_string(recipient)
    safe_message = _escape_applescript_string(message)

    # AppleScript to send message via Messages.app
    applescript = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{safe_recipient}" of targetService
        send "{safe_message}" to targetBuddy
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            return SendResult(success=False, error=error_msg)

        return SendResult(success=True)

    except subprocess.TimeoutExpired:
        return SendResult(success=False, error="Timeout: Messages.app did not respond")
    except Exception as e:
        return SendResult(success=False, error=str(e))
