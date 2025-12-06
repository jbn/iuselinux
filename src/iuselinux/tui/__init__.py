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

    @click.command()
    @click.option(
        "--host",
        "-h",
        default="localhost",
        help="Server hostname",
        show_default=True,
    )
    @click.option(
        "--port",
        "-p",
        default=8000,
        type=int,
        help="Server port",
        show_default=True,
    )
    @click.option(
        "--token",
        "-t",
        default=None,
        help="API authentication token",
        envvar="IUSELINUX_TOKEN",
    )
    def run_tui(host: str, port: int, token: str | None) -> None:
        """iMessage Gateway TUI client.

        Connect to a running iMessage Gateway server and interact via terminal UI.
        """
        try:
            from iuselinux.tui.app import IMessageApp
        except ImportError as e:
            print(
                "TUI dependencies not installed. Install with: pip install iuselinux[tui]",
                file=sys.stderr,
            )
            print(f"Missing: {e.name}", file=sys.stderr)
            sys.exit(1)

        app = IMessageApp(host=host, port=port, token=token)
        app.run()

    run_tui()


if __name__ == "__main__":
    main()
