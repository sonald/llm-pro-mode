"""Configuration management for LLM Pro Mode."""

import os
from dataclasses import dataclass
from typing import Optional
from rich.console import Console
from dotenv import load_dotenv

from .profile_manager import ProfileManager, ProfileConfig

# Load environment variables
load_dotenv()

@dataclass
class Config:
    """Application configuration with profile support."""

    model_name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    n_runs: int = 3
    port: int = 8000
    trace_enabled: bool = False
    trace_dir: str = "traces"
    trace_compact: bool = False

    # Profile-related settings
    profile_name: Optional[str] = None
    config_file_path: Optional[str] = None
    profile_manager: Optional[ProfileManager] = None

    # Keep original API key value for saving (before env var resolution)
    _original_api_key: Optional[str] = None

    def __post_init__(self):
        """Initialize configuration from various sources with proper priority."""
        # Initialize profile manager if not provided
        if self.profile_manager is None:
            self.profile_manager = ProfileManager(self.config_file_path)

        # Load configuration in priority order:
        # 1. Command line args (handled in update_from_args)
        # 2. JSON profile (if specified)
        # 3. Environment variables (fallback)
        # 4. Default values (already set)

        self._load_from_profile()
        self._load_from_env_if_missing()

    def _load_from_profile(self):
        """Load configuration from JSON profile if available."""
        if not self.profile_manager:
            return

        profile = None
        if self.profile_name:
            # Use specified profile
            profile = self.profile_manager.get_profile(self.profile_name)
            if not profile:
                console.print(f"[red]Profile '{self.profile_name}' 不存在，使用默认配置[/red]")
                profile = self.profile_manager.get_default_profile()
        else:
            # Use default profile
            profile = self.profile_manager.get_default_profile()

        if profile:
            # Only update if not already set (preserves command line args)
            if self.model_name is None:
                self.model_name = profile.model_name
            if self.api_base is None:
                self.api_base = profile.api_base
            if self.api_key is None:
                # Keep original value for saving purposes
                self._original_api_key = profile.api_key
                # If api_key looks like an environment variable name, resolve it
                self.api_key = self._resolve_api_key(profile.api_key)

    def _resolve_api_key(self, api_key_value: str) -> str:
        """Resolve API key from environment variable if it's a variable name."""
        if not api_key_value:
            return api_key_value

        # If the value looks like an environment variable name (uppercase, underscores)
        # and doesn't start with known API key prefixes, treat it as env var name
        if (api_key_value.isupper() and
            '_' in api_key_value and
            not api_key_value.startswith(('sk-', 'sk_', 'xai-', 'ant-'))):
            env_value = os.getenv(api_key_value)
            if env_value:
                return env_value
            else:
                # If env var doesn't exist, keep original value and show warning
                console.print(f"[yellow]警告：环境变量 '{api_key_value}' 未设置[/yellow]")
                return ""

        # Otherwise, treat as literal API key value
        return api_key_value

    def _load_from_env_if_missing(self):
        """Load from environment variables if values are still missing."""
        if self.model_name is None:
            self.model_name = os.getenv("LLM_PRO_MODEL")
        if self.api_base is None:
            self.api_base = os.getenv("LLM_PRO_API_BASE")
        if self.api_key is None:
            env_api_key = os.getenv("LLM_PRO_API_KEY")
            if env_api_key:
                self.api_key = self._resolve_api_key(env_api_key)

    def update_from_args(self, args) -> None:
        """Update configuration from command line arguments."""
        # Update profile settings first
        if hasattr(args, 'profile') and args.profile:
            self.profile_name = args.profile
        if hasattr(args, 'config') and args.config:
            self.config_file_path = args.config
            # Reinitialize profile manager with new config path
            self.profile_manager = ProfileManager(self.config_file_path)

        # Update core configuration (highest priority)
        if hasattr(args, 'model') and args.model:
            self.model_name = args.model
        if hasattr(args, 'api_base') and args.api_base:
            self.api_base = args.api_base
        if hasattr(args, 'api_key') and args.api_key:
            self._original_api_key = args.api_key
            self.api_key = self._resolve_api_key(args.api_key)
        if hasattr(args, 'n_runs') and args.n_runs:
            self.n_runs = args.n_runs
        if hasattr(args, 'port') and args.port:
            self.port = args.port
        if hasattr(args, 'trace') and args.trace:
            self.trace_enabled = args.trace
        if hasattr(args, 'trace_dir') and args.trace_dir:
            self.trace_dir = args.trace_dir
        if hasattr(args, 'trace_compact') and args.trace_compact:
            self.trace_compact = args.trace_compact

        # Reload configuration after args update to apply profile changes
        if hasattr(args, 'profile') or hasattr(args, 'config'):
            # Clear values that would come from profile to allow reload
            if not (hasattr(args, 'model') and args.model):
                self.model_name = None
            if not (hasattr(args, 'api_base') and args.api_base):
                self.api_base = None
            if not (hasattr(args, 'api_key') and args.api_key):
                self.api_key = None
            self._load_from_profile()
            self._load_from_env_if_missing()

    def save_current_as_profile(self, profile_name: str, description: str = "") -> bool:
        """Save current configuration as a new profile."""
        if not self.profile_manager:
            return False

        # Use original API key value for saving, or resolved value if no original
        api_key_to_save = self._original_api_key if self._original_api_key else self.api_key

        if not all([self.model_name, self.api_base, api_key_to_save]):
            console.print("[red]当前配置不完整，无法保存为 profile[/red]")
            return False

        profile = ProfileConfig(
            model_name=self.model_name,
            api_base=self.api_base,
            api_key=api_key_to_save,
            description=description
        )

        return self.profile_manager.add_profile(profile_name, profile)

    def get_effective_config_summary(self) -> str:
        """Get a summary of the effective configuration and its sources."""
        summary = []

        if self.profile_name:
            summary.append(f"Profile: {self.profile_name}")

        if self.config_file_path:
            summary.append(f"Config file: {self.config_file_path}")
        elif self.profile_manager:
            summary.append(f"Config file: {self.profile_manager.config_path}")

        summary.append(f"Model: {self.model_name or 'Not set'}")
        summary.append(f"API Base: {self.api_base or 'Not set'}")

        api_key_status = "Set" if self.api_key else "Not set"
        if self.api_key:
            api_key_status += f" ({self.api_key[:8]}...)"
        summary.append(f"API Key: {api_key_status}")

        return " | ".join(summary)

# Global console instance for rich output
console = Console()

# Global configuration instance
config = Config()