"""Runtime configuration assembly utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from dotenv import load_dotenv

from ..config import Config
from ..logger import get_logger
from ..profile_manager import ProfileConfig, ProfileManager


_logger = get_logger()


@dataclass
class RuntimeState:
    """Holds runtime configuration alongside profile management helpers."""

    config: Config
    profile_manager: ProfileManager
    api_key_source: Optional[str] = None

    def api_key_preview(self) -> str:
        """Return a safe preview string for the current API key state."""
        if not self.config.api_key:
            return "Not set"

        if self.api_key_source and _looks_like_env_var(self.api_key_source):
            return f"Env: {self.api_key_source}"

        value = self.config.api_key
        if value is None or value == "":
            return "Not set"
        if len(value) <= 6:
            return f"Set ({value[:2]}***)"
        return f"Set ({value[:4]}...{value[-2:]})"

    def summary(self) -> str:
        """Return human-readable summary of the runtime configuration."""
        return self.config.summary(
            config_path=str(self.profile_manager.config_path)
            if self.profile_manager and self.profile_manager.config_path
            else None,
            api_key_preview=self.api_key_preview(),
        )

    def save_profile(self, profile_name: str, description: str = "") -> bool:
        """Persist the current configuration as a profile."""
        api_key_to_save = self.api_key_source or self.config.api_key

        if not all([self.config.model_name, self.config.api_base, api_key_to_save]):
            _logger.error("当前配置不完整，无法保存为 profile")
            return False

        profile = ProfileConfig(
            model_name=self.config.model_name,
            api_base=self.config.api_base,
            api_key=api_key_to_save,
            description=description,
        )

        return self.profile_manager.add_profile(profile_name, profile)

    def set_default_profile(self, profile_name: str) -> bool:
        """Mark the provided profile as default if it exists."""
        return self.profile_manager.set_default_profile(profile_name)

    def delete_profile(self, profile_name: str) -> bool:
        """Delete a profile by name."""
        return self.profile_manager.delete_profile(profile_name)

    def list_profiles(self) -> None:
        """Render profile list using the manager's presentation helpers."""
        self.profile_manager.list_profiles()

    def show_profile(self, profile_name: str) -> None:
        """Display a profile."""
        self.profile_manager.show_profile(profile_name)

    def _apply_profile(self, profile_name: Optional[str]) -> None:
        """Apply configuration from the selected profile if available."""
        if not profile_name:
            return

        profile = self.profile_manager.get_profile(profile_name)
        if not profile:
            _logger.warning(
                "Profile '%s' 不存在，使用默认配置代替", profile_name
            )
            return

        self.config.profile_name = profile_name
        self._apply_profile_values(profile)

    def _apply_profile_values(self, profile: ProfileConfig) -> None:
        self.config.model_name = self.config.model_name or profile.model_name
        self.config.api_base = self.config.api_base or profile.api_base
        self.api_key_source = profile.api_key
        resolved_key = _resolve_api_key(profile.api_key)
        if resolved_key:
            self.config.api_key = resolved_key

    def populate_from_profile(self, requested_profile: Optional[str]) -> None:
        """Load configuration values from a profile selection."""
        config_file = self.profile_manager.load_config()

        if requested_profile:
            self._apply_profile(requested_profile)
            if self.config.profile_name:
                return

        default_profile = config_file.default_profile
        if default_profile:
            self._apply_profile(default_profile)

    def active_profile_name(self) -> Optional[str]:
        """Return the currently active profile name, if any."""
        if self.config.profile_name:
            return self.config.profile_name

        config_file = self.profile_manager.load_config()
        return config_file.default_profile or None

    def apply_profile(self, profile_name: str, *, make_default: bool = False) -> bool:
        profile = self.profile_manager.get_profile(profile_name)
        if not profile:
            return False

        self.config.profile_name = profile_name
        self.config.model_name = profile.model_name
        self.config.api_base = profile.api_base
        self.api_key_source = profile.api_key
        resolved_key = _resolve_api_key(profile.api_key)
        if resolved_key:
            self.config.api_key = resolved_key

        if make_default:
            config_file = self.profile_manager.load_config()
            config_file.default_profile = profile_name
            self.profile_manager.config_file = config_file
            self.profile_manager.save_config()

        return True

    def apply_environment(self, environ: Mapping[str, str]) -> None:
        """Fill missing configuration fields from environment variables."""
        if not self.config.model_name:
            self.config.model_name = environ.get("LLM_PRO_MODEL")

        if not self.config.api_base:
            self.config.api_base = environ.get("LLM_PRO_API_BASE")

        if not self.config.api_key:
            env_api_key = environ.get("LLM_PRO_API_KEY")
            if env_api_key:
                resolved_key = _resolve_api_key(env_api_key)
                if resolved_key:
                    self.config.api_key = resolved_key

        self._apply_numeric_env(environ)

    def apply_overrides_from_args(self, args) -> None:
        """Apply highest-priority overrides provided by CLI arguments."""
        if args is None:
            return

        if getattr(args, "profile", None):
            self.config.profile_name = args.profile

        if getattr(args, "model", None):
            self.config.model_name = args.model

        if getattr(args, "api_base", None):
            self.config.api_base = args.api_base

        if getattr(args, "api_key", None):
            self.api_key_source = args.api_key
            resolved_key = _resolve_api_key(args.api_key)
            if resolved_key:
                self.config.api_key = resolved_key

        if getattr(args, "n_runs", None):
            self.config.n_runs = args.n_runs

        if getattr(args, "port", None):
            self.config.port = args.port

        if getattr(args, "trace", None):
            self.config.trace_enabled = bool(args.trace)

        if getattr(args, "trace_dir", None):
            self.config.trace_dir = args.trace_dir

        if getattr(args, "trace_compact", None):
            self.config.trace_compact = bool(args.trace_compact)

        if getattr(args, "temperature", None) is not None:
            self.config.temperature = args.temperature

        if getattr(args, "synthesis_temperature", None) is not None:
            self.config.synthesis_temperature = args.synthesis_temperature

        if getattr(args, "max_tokens", None) is not None:
            self.config.max_tokens = args.max_tokens

    def _apply_numeric_env(self, environ: Mapping[str, str]) -> None:
        temp = environ.get("LLM_PRO_TEMPERATURE")
        if temp:
            try:
                self.config.temperature = float(temp)
            except ValueError:
                _logger.warning("LLM_PRO_TEMPERATURE 非法，使用默认值")

        synth_temp = environ.get("LLM_PRO_SYNTH_TEMPERATURE")
        if synth_temp:
            try:
                self.config.synthesis_temperature = float(synth_temp)
            except ValueError:
                _logger.warning("LLM_PRO_SYNTH_TEMPERATURE 非法，使用默认值")

        max_tokens = environ.get("LLM_PRO_MAX_TOKENS")
        if max_tokens:
            try:
                self.config.max_tokens = int(max_tokens)
            except ValueError:
                _logger.warning("LLM_PRO_MAX_TOKENS 非法，忽略该配置")


class ConfigLoader:
    """Build runtime configuration from CLI arguments and environment."""

    def __init__(self, *, profile_manager_cls=ProfileManager):
        self._profile_manager_cls = profile_manager_cls

    def load(self, args=None) -> RuntimeState:
        load_dotenv()

        config_path = getattr(args, "config", None)
        profile_manager = self._profile_manager_cls(config_path)

        config = Config()
        config.config_file_path = config_path or str(profile_manager.config_path)

        state = RuntimeState(config=config, profile_manager=profile_manager)

        requested_profile = getattr(args, "profile", None)
        state.populate_from_profile(requested_profile)

        state.apply_environment(os.environ)
        state.apply_overrides_from_args(args)

        return state


def _looks_like_env_var(value: str) -> bool:
    return (
        value.isupper()
        and "_" in value
        and not value.startswith(("sk-", "sk_", "xai-", "ant-"))
    )


def _resolve_api_key(api_key_value: Optional[str]) -> Optional[str]:
    if not api_key_value:
        return None

    if _looks_like_env_var(api_key_value):
        env_value = os.getenv(api_key_value)
        if env_value:
            return env_value
        _logger.warning("环境变量 '%s' 未设置", api_key_value)
        return None

    return api_key_value
