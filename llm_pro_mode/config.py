"""Backward compatibility layer for the legacy config module."""

from .config import Config, ConfigLoader, RuntimeState

__all__ = ["Config", "ConfigLoader", "RuntimeState"]
