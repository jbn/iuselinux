"""Custom hatchling build hook to enforce macOS-only wheel.

This hook sets the wheel platform tag to macosx, which means:
- pip/uv will refuse to install on Linux/Windows
- The error message will indicate the package is not compatible with the platform
"""

import sys
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build hook that sets macOS-specific platform tags."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        """Set the wheel tag to be macOS-specific.

        This makes pip/uv refuse to install on non-macOS platforms with an error like:
        "ERROR: iuselinux-0.1.4-py3-none-macosx_10_9_universal2.whl is not a supported
        wheel on this platform."
        """
        # Only modify wheel builds, not sdist
        if self.target_name != "wheel":
            return

        # Set platform-specific tag for macOS
        # Format: {python_tag}-{abi_tag}-{platform_tag}
        # - py3: works with any Python 3
        # - none: no ABI requirements (pure Python)
        # - macosx_10_9_universal2: macOS 10.9+ on both Intel and Apple Silicon
        build_data["tag"] = "py3-none-macosx_10_9_universal2"
