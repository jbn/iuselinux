"""TUI client for iMessage Gateway using Textual."""

from __future__ import annotations

import sys


def main() -> None:
    """Entry point for the TUI client."""
    try:
        import click
    except ImportError:
        print(
            "TUI dependencies not installed. Install with: pip install iuselinux[tui]",
            file=sys.stderr,
        )
        sys.exit(1)

    from iuselinux.config import get_config

    # Load saved settings as defaults
    config = get_config()
    default_host = config.get("tui_server_host", "localhost")
    default_port = config.get("tui_server_port", 8000)
    default_token = config.get("api_token") or None
    default_theme = config.get("tui_theme", "auto")

    @click.command()
    @click.option(
        "--host",
        "-h",
        default=default_host,
        help="Server hostname",
        show_default=True,
    )
    @click.option(
        "--port",
        "-p",
        default=default_port,
        type=int,
        help="Server port",
        show_default=True,
    )
    @click.option(
        "--token",
        "-t",
        default=default_token,
        help="API authentication token",
        envvar="IUSELINUX_TOKEN",
    )
    @click.option(
        "--theme",
        type=click.Choice(["auto", "dark", "light"]),
        default=default_theme,
        help="Color theme",
        show_default=True,
    )
    @click.option(
        "--save",
        is_flag=True,
        help="Save host/port/token/theme to config for future sessions",
    )
    @click.option(
        "--debug",
        is_flag=True,
        help="Enable debug logging to /tmp/imessage-tui.log",
    )
    def run_tui(host: str, port: int, token: str | None, theme: str, save: bool, debug: bool) -> None:
        """iMessage Gateway TUI client.

        Connect to a running iMessage Gateway server and interact via terminal UI.
        """
        # Configure logging before imports
        if debug:
            import logging
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s %(name)s %(levelname)s: %(message)s",
                filename="/tmp/imessage-tui.log",
                filemode="w",
            )
            logging.getLogger("iuselinux").setLevel(logging.DEBUG)

        try:
            from iuselinux.tui.app import IMessageApp
            from iuselinux.tui.themes import ThemeMode
        except ImportError as e:
            print(
                "TUI dependencies not installed. Install with: pip install iuselinux[tui]",
                file=sys.stderr,
            )
            print(f"Missing: {e.name}", file=sys.stderr)
            sys.exit(1)

        # Save settings if requested
        if save:
            from iuselinux.config import update_config

            updates = {
                "tui_server_host": host,
                "tui_server_port": port,
                "tui_theme": theme,
            }
            if token:
                updates["api_token"] = token
            update_config(updates)
            print(f"Saved settings: {host}:{port} (theme={theme})", file=sys.stderr)

        # Convert theme string to enum
        theme_mode = ThemeMode(theme)

        app = IMessageApp(host=host, port=port, token=token, theme_mode=theme_mode)
        app.run()

    run_tui()


if __name__ == "__main__":
    main()
