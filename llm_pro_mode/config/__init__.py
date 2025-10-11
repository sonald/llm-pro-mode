"""Configuration package for LLM Pro Mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Application configuration assembled at runtime."""

    model_name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    n_runs: int = 3
    port: int = 8000
    trace_enabled: bool = False
    trace_dir: str = "traces"
    trace_compact: bool = False
    temperature: float = 0.9
    synthesis_temperature: float = 0.2
    max_tokens: Optional[int] = None

    # Metadata about how the config was produced
    profile_name: Optional[str] = None
    config_file_path: Optional[str] = None

    def summary(
        self,
        *,
        config_path: Optional[str] = None,
        api_key_preview: Optional[str] = None,
    ) -> str:
        """Render a short textual summary of the effective configuration."""

        summary_parts: list[str] = []

        if self.profile_name:
            summary_parts.append(f"Profile: {self.profile_name}")

        if config_path:
            summary_parts.append(f"Config file: {config_path}")
        elif self.config_file_path:
            summary_parts.append(f"Config file: {self.config_file_path}")

        summary_parts.append(f"Model: {self.model_name or 'Not set'}")
        summary_parts.append(f"API Base: {self.api_base or 'Not set'}")

        if api_key_preview:
            summary_parts.append(f"API Key: {api_key_preview}")
        else:
            summary_parts.append("API Key: Hidden")

        summary_parts.append(f"Temperature: {self.temperature}")
        summary_parts.append(f"Synthesis Temp: {self.synthesis_temperature}")
        summary_parts.append(f"Max Tokens: {self.max_tokens or 'Unlimited'}")

        return " | ".join(summary_parts)


from .runtime import ConfigLoader, RuntimeState  # noqa: E402

__all__ = ["Config", "ConfigLoader", "RuntimeState"]
