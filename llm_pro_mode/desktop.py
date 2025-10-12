"""Desktop helpers for running the Web UI inside a Tauri shell."""

from __future__ import annotations

import argparse
import contextlib
import socket
from dataclasses import dataclass
from typing import Optional

import uvicorn


@dataclass(slots=True)
class DesktopServerConfig:
    """Configuration options for launching the embedded web server."""

    host: str = "127.0.0.1"
    port: Optional[int] = None
    log_level: str = "info"


def find_available_port(start: int = 4000, end: int = 4999) -> int:
    """Find an available localhost port for the desktop server."""

    for port in range(start, end + 1):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue

    # Fallback to system-assigned port if preferred range exhausted
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_desktop_server(config: DesktopServerConfig) -> None:
    """Launch the FastAPI Web UI under uvicorn for the desktop shell."""

    # Initialize runtime configuration before starting the server
    from .config.runtime import ConfigLoader
    from .interfaces.web import app as web_app, configure_runtime

    # Load configuration from environment and profiles
    config_loader = ConfigLoader()
    runtime_state = config_loader.load()

    # Configure the web interface runtime context
    configure_runtime(runtime_state)

    host = config.host
    port = config.port or find_available_port()

    uvicorn.run(
        web_app,
        host=host,
        port=port,
        log_level=config.log_level,
        reload=False,
    )


def main(argv: Optional[list[str]] = None) -> None:
    """CLI entry point so the module can be invoked via ``python -m``."""

    parser = argparse.ArgumentParser(
        description="Run the LLM Pro Mode web interface for the desktop shell",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind")
    parser.add_argument(
        "--log-level",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        default="info",
        help="uvicorn log level",
    )

    args = parser.parse_args(argv)
    config = DesktopServerConfig(host=args.host, port=args.port, log_level=args.log_level)
    run_desktop_server(config)


if __name__ == "__main__":
    main()
