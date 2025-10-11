"""Shared runtime state management for interface modules."""

from __future__ import annotations

from typing import Optional

from ..config import Config
from ..config.runtime import RuntimeState


class RuntimeContext:
    """Manages runtime state for an interface module.

    Provides centralized state management and configuration access
    for API, Web, and other interface implementations.
    """

    def __init__(self, interface_name: str = "Interface"):
        self._interface_name = interface_name
        self._runtime_state: Optional[RuntimeState] = None

    def configure(self, state: RuntimeState) -> None:
        """Configure the runtime state for this interface."""
        self._runtime_state = state

    def require_state(self) -> RuntimeState:
        """Get the configured runtime state, raising if not configured."""
        if self._runtime_state is None:
            raise RuntimeError(f"{self._interface_name} runtime state not configured")
        return self._runtime_state

    def get_config(self) -> Config:
        """Get the current configuration."""
        return self.require_state().config

    @property
    def is_configured(self) -> bool:
        """Check if runtime state is configured."""
        return self._runtime_state is not None
