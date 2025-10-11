"""Profile management for LLM Pro Mode configurations."""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List
from rich.table import Table
from rich.panel import Panel

from .logger import console, error, warning


@dataclass
class ProfileConfig:
    """Single profile configuration."""

    model_name: str
    api_base: str
    api_key: str
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProfileConfig':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ConfigFile:
    """Complete configuration file structure."""

    default_profile: str
    profiles: Dict[str, ProfileConfig]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'default_profile': self.default_profile,
            'profiles': {name: profile.to_dict() for name, profile in self.profiles.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigFile':
        """Create from dictionary."""
        profiles = {
            name: ProfileConfig.from_dict(profile_data)
            for name, profile_data in data.get('profiles', {}).items()
        }
        return cls(
            default_profile=data.get('default_profile', ''),
            profiles=profiles
        )


class ProfileManager:
    """Manages configuration profiles and JSON files."""

    DEFAULT_CONFIG_DIRS = [
        Path.home() / '.llm-pro-mode',
        Path.cwd(),
    ]
    DEFAULT_CONFIG_NAME = 'config.json'
    LOCAL_CONFIG_NAME = 'llm_pro_config.json'

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize ProfileManager.

        Args:
            config_path: Custom config file path, if None uses default search
        """
        self.config_path = self._resolve_config_path(config_path)
        self.config_file: Optional[ConfigFile] = None

    def _resolve_config_path(self, custom_path: Optional[str] = None) -> Path:
        """Resolve configuration file path."""
        if custom_path:
            return Path(custom_path)

        # Check for local config first
        local_config = Path.cwd() / self.LOCAL_CONFIG_NAME
        if local_config.exists():
            return local_config

        # Check default locations
        for config_dir in self.DEFAULT_CONFIG_DIRS:
            config_file = config_dir / self.DEFAULT_CONFIG_NAME
            if config_file.exists():
                return config_file

        # Default to user home directory
        default_dir = self.DEFAULT_CONFIG_DIRS[0]
        return default_dir / self.DEFAULT_CONFIG_NAME

    def _create_default_config(self) -> ConfigFile:
        """Create default configuration with sample profiles."""
        return ConfigFile(
            default_profile='grok',
            profiles={
                'grok': ProfileConfig(
                    model_name='x-ai/grok-2-vision-1212',
                    api_base='https://openrouter.ai/api/v1',
                    api_key='OPENROUTER_API_KEY',
                    description='OpenRouter Grok Code 模型配置'
                ),
                'openai': ProfileConfig(
                    model_name='gpt-4',
                    api_base='https://api.openai.com/v1',
                    api_key='OPENAI_API_KEY',
                    description='OpenAI GPT-4 配置'
                ),
                'anthropic': ProfileConfig(
                    model_name='claude-3-sonnet',
                    api_base='https://api.anthropic.com',
                    api_key='ANTHROPIC_API_KEY',
                    description='Anthropic Claude 配置'
                ),
                'deepseek': ProfileConfig(
                    model_name='deepseek-chat',
                    api_base='https://api.deepseek.com/v1',
                    api_key='DEEPSEEK_API_KEY',
                    description='DeepSeek 模型配置'
                )
            }
        )

    def load_config(self) -> ConfigFile:
        """Load configuration from file, create default if doesn't exist."""
        if not self.config_path.exists():
            warning("配置文件不存在，创建默认配置: %s", self.config_path)
            self.config_file = self._create_default_config()
            self.save_config()
            return self.config_file

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.config_file = ConfigFile.from_dict(data)
            return self.config_file
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            error("配置文件格式错误: %s", e)
            warning("使用默认配置替换")
            self.config_file = self._create_default_config()
            return self.config_file

    def save_config(self) -> bool:
        """Save configuration to file."""
        if not self.config_file:
            return False

        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_file.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            error("保存配置文件失败: %s", e)
            return False

    def get_profile(self, profile_name: str) -> Optional[ProfileConfig]:
        """Get profile by name."""
        if not self.config_file:
            self.load_config()

        return self.config_file.profiles.get(profile_name)

    def get_default_profile(self) -> Optional[ProfileConfig]:
        """Get the default profile."""
        if not self.config_file:
            self.load_config()

        if not self.config_file.default_profile:
            return None

        return self.get_profile(self.config_file.default_profile)

    def add_profile(self, name: str, profile: ProfileConfig) -> bool:
        """Add or update a profile."""
        if not self.config_file:
            self.load_config()

        self.config_file.profiles[name] = profile
        return self.save_config()

    def delete_profile(self, name: str) -> bool:
        """Delete a profile."""
        if not self.config_file:
            self.load_config()

        if name not in self.config_file.profiles:
            error("Profile '%s' 不存在", name)
            return False

        # Don't delete if it's the default profile
        if name == self.config_file.default_profile:
            error("不能删除默认 profile '%s'", name)
            return False

        del self.config_file.profiles[name]
        return self.save_config()

    def set_default_profile(self, name: str) -> bool:
        """Set default profile."""
        if not self.config_file:
            self.load_config()

        if name not in self.config_file.profiles:
            error("Profile '%s' 不存在", name)
            return False

        self.config_file.default_profile = name
        return self.save_config()

    def list_profiles(self) -> None:
        """Display all available profiles."""
        if not self.config_file:
            self.load_config()

        table = Table(title="可用的配置 Profiles")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Model", style="magenta")
        table.add_column("API Base", style="blue")
        table.add_column("Description", style="green")
        table.add_column("Default", style="yellow")

        for name, profile in self.config_file.profiles.items():
            is_default = "✓" if name == self.config_file.default_profile else ""
            # Mask API key for security
            api_base = profile.api_base[:50] + "..." if len(profile.api_base) > 50 else profile.api_base

            table.add_row(
                name,
                profile.model_name,
                api_base,
                profile.description or "",
                is_default
            )

        console.print(table)
        console.print(f"\n[dim]配置文件路径: {self.config_path}[/dim]")

    def show_profile(self, name: str) -> None:
        """Show detailed profile information."""
        profile = self.get_profile(name)
        if not profile:
            error("Profile '%s' 不存在", name)
            return

        # Mask API key for security
        masked_key = profile.api_key[:8] + "..." if len(profile.api_key) > 8 else profile.api_key

        content = f"""[bold cyan]Model:[/bold cyan] {profile.model_name}
[bold cyan]API Base:[/bold cyan] {profile.api_base}
[bold cyan]API Key:[/bold cyan] {masked_key}
[bold cyan]Description:[/bold cyan] {profile.description or 'No description'}"""

        is_default = name == self.config_file.default_profile
        title = f"Profile: {name}" + (" (Default)" if is_default else "")

        panel = Panel(content, title=title, border_style="blue")
        console.print(panel)

    def get_profile_names(self) -> List[str]:
        """Get list of all profile names."""
        if not self.config_file:
            self.load_config()

        return list(self.config_file.profiles.keys())