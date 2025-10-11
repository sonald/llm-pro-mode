"""Shared logging utilities for LLM Pro Mode."""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.logging import RichHandler


_console = Console()


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("llm_pro_mode")
    if logger.handlers:
        return logger

    handler = RichHandler(console=_console, rich_tracebacks=True, markup=True)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    return logger


_logger = _build_logger()


def get_logger() -> logging.Logger:
    return _logger


def get_console() -> Console:
    return _console


def info(message: str, *args: Any, **kwargs: Any) -> None:
    _logger.info(message, *args, **kwargs)


def warning(message: str, *args: Any, **kwargs: Any) -> None:
    _logger.warning(message, *args, **kwargs)


def error(message: str, *args: Any, **kwargs: Any) -> None:
    _logger.error(message, *args, **kwargs)


def debug(message: str, *args: Any, **kwargs: Any) -> None:
    _logger.debug(message, *args, **kwargs)


def success(message: str, *args: Any, **kwargs: Any) -> None:
    _logger.info("[bold green]%s[/bold green]", message, *args, **kwargs)


# Convenience alias to keep compatibility with Rich output when needed
console = _console
