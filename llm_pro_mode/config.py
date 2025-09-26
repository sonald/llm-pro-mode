"""Configuration management for LLM Pro Mode."""

import os
from dataclasses import dataclass
from typing import Optional
from rich.console import Console
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class Config:
    """Application configuration."""

    model_name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    n_runs: int = 3
    port: int = 8000
    trace_enabled: bool = False
    trace_dir: str = "traces"
    trace_compact: bool = False

    def __post_init__(self):
        """Initialize configuration from environment variables if not set."""
        if self.model_name is None:
            self.model_name = os.getenv("LLM_PRO_MODEL")
        if self.api_base is None:
            self.api_base = os.getenv("LLM_PRO_API_BASE")
        if self.api_key is None:
            self.api_key = os.getenv("LLM_PRO_API_KEY")

    def update_from_args(self, args) -> None:
        """Update configuration from command line arguments."""
        if args.model:
            self.model_name = args.model
        if args.api_base:
            self.api_base = args.api_base
        if args.api_key:
            self.api_key = args.api_key
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

# Global console instance for rich output
console = Console()

# Global configuration instance
config = Config()