# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM Pro Mode is a modular Python application that provides multiple interfaces (CLI, TUI, and FastAPI server) for running parallel LLM completions and synthesizing results. The project follows a clean, modular architecture with separated concerns.

## Architecture

### Modular Package Structure

```
llm_pro_mode/
├── __init__.py              # Package initialization
├── main.py                  # Main entry point and CLI argument parsing
├── config.py                # Configuration management and global state
├── profile_manager.py       # JSON profile configuration system
├── core/                    # Core business logic
│   ├── __init__.py
│   ├── llm_client.py        # LLM API calls and streaming
│   ├── synthesizer.py       # Result synthesis logic
│   └── processor.py         # Main processing coordination
├── tracing/                 # Debugging and logging
│   ├── __init__.py
│   ├── logger.py            # TraceLogger for debugging
│   └── yaml_dumper.py       # Custom YAML serialization
├── interfaces/              # User interfaces
│   ├── __init__.py
│   ├── api.py              # FastAPI web server
│   ├── cli.py              # Command-line interface
│   └── tui.py              # Terminal user interface
└── models/                 # Data models
    ├── __init__.py
    └── schemas.py          # Pydantic models
```

### Design Principles

**Separation of Concerns**: Each module has a single responsibility:
- `config.py`: Centralized configuration management with environment variable and CLI argument support
- `profile_manager.py`: JSON-based configuration profiles with multi-location file resolution
- `core/`: Business logic and LLM processing
- `interfaces/`: User interaction layers
- `tracing/`: Debugging and logging utilities
- `models/`: Data structures and validation

**Dependency Injection**: Global state is managed through the config module, eliminating global variables and improving testability.

**Flexible Configuration**: Multi-layer configuration system supporting environment variables, JSON profiles, and command-line arguments with clear precedence rules.

**Multi-Interface Design**: Three distinct modes of operation:
- CLI mode: Direct command-line execution with progress bars
- TUI mode: Interactive terminal interface using Textual framework
- Server mode: FastAPI web server for HTTP API access

**Parallel Processing**: Uses `anyio` task groups to run multiple LLM calls concurrently, then synthesizes results using a separate LLM call.

## Development Commands

### Installation and Setup

**Install as package** (recommended for development):
```bash
pip install -e .
```

**Direct module execution**:
```bash
python -m llm_pro_mode.main
```

**Direct script execution** (without installation):
```bash
python llm_pro.py
```

### Running the Application

**CLI Mode (default)**:
```bash
llm-pro-mode --prompt "Your prompt here" --model "model-name"
# or
python -m llm_pro_mode.main --prompt "Your prompt here" --model "model-name"
```

**Terminal UI Mode**:
```bash
llm-pro-mode --tui
# or
python -m llm_pro_mode.main --tui
```

**Server Mode**:
```bash
llm-pro-mode --serve --port 8000
# or
python -m llm_pro_mode.main --serve --port 8000
```

### Environment Variables

Set these environment variables or pass as arguments:
- `LLM_PRO_MODEL`: Default model name
- `LLM_PRO_API_BASE`: API base URL
- `LLM_PRO_API_KEY`: API key

### Profile Management System

The application includes a JSON-based profile management system that allows saving and reusing different API configurations:

**Configuration file locations** (checked in order):
1. `./llm_pro_config.json` (project-local config)
2. `~/.llm-pro-mode/config.json` (user config)
3. `./config.json` (fallback)

**Profile commands**:
```bash
# List all available profiles
llm-pro-mode --list-profiles

# Show specific profile details
llm-pro-mode --show-profile openai

# Use a specific profile
llm-pro-mode --profile grok --prompt "Your prompt here"

# Save current configuration as a new profile
llm-pro-mode --save-profile my-config --model "gpt-4" --api_base "https://api.openai.com/v1"

# Set default profile
llm-pro-mode --set-default-profile openai

# Delete a profile
llm-pro-mode --delete-profile old-config
```

**Configuration priority** (highest to lowest):
1. Command line arguments
2. JSON profile configuration
3. Environment variables
4. Default values

### Stdin Support

The CLI mode supports reading prompts from stdin:
```bash
# Read from stdin with '-' flag
echo "Explain machine learning" | llm-pro-mode -p -

# Read from file via stdin
llm-pro-mode -p - < input.txt

# Interactive stdin input
llm-pro-mode --prompt -
# (then type your prompt and press Ctrl+D)
```

### Testing and Debug

**Enable trace logging**:
```bash
python llm-pro-mode.py --trace --prompt "test"
```

**Compact trace mode**:
```bash
python llm-pro-mode.py --trace --trace_compact --prompt "test"
```

### Dependencies

The project dependencies are defined in `pyproject.toml` and include:
- `anyio`: Async concurrency framework
- `python-dotenv`: Environment variable loading
- `fastapi`: Web API framework
- `litellm`: LLM API integration
- `pydantic`: Data validation
- `rich`: Terminal output formatting
- `textual`: Terminal UI framework
- `uvicorn`: ASGI server
- `pyyaml`: YAML serialization

Install dependencies with:
```bash
pip install -e .
```

## Configuration

### Command-Line Options

- `--model, -m`: LLM model name
- `--api_base, -b`: API base URL
- `--api_key, -k`: API key
- `--prompt, -p`: Input prompt (CLI mode)
- `--n_runs, -n`: Number of parallel runs (default: 3)
- `--port, -P`: Server port (default: 8000)
- `--serve`: Enable server mode
- `--tui`: Enable terminal UI mode
- `--trace, -t`: Enable trace logging
- `--trace_dir`: Trace output directory
- `--trace_compact, --tc`: Use compact trace format

### TUI Key Bindings

- `Ctrl+J`: Submit prompt
- `Enter`: New line in input
- `Ctrl+C/Q`: Quit
- `Ctrl+L`: Clear results
- `↑↓/PgUp/PgDn`: Scroll results
- Emacs-style editing: `Ctrl+A/E`, `Ctrl+P/N`, `Ctrl+K`

## Code Patterns

### Modular Architecture

The application follows clean architecture principles:
- **Config Module**: Centralized configuration using dataclasses with environment variable support
- **Dependency Injection**: Configuration and trace loggers are passed as parameters rather than using global state
- **Interface Separation**: Each UI mode (CLI, TUI, API) is implemented in separate modules
- **Core Logic Isolation**: Business logic is separated from interface concerns

### Async Task Management

The application uses `anyio.create_task_group()` for structured concurrency in `core/processor.py`, spawning multiple LLM calls in parallel and collecting results.

### Progress Tracking

Multiple progress tracking implementations:
- Rich-based progress bars for CLI mode (`interfaces/cli.py`)
- Custom TUI progress widgets for terminal interface (`interfaces/tui.py`)
- Status tracking for API mode (`interfaces/api.py`)

### Error Handling

Comprehensive error handling with optional trace logging integration:
- TraceLogger instances are created per operation when needed
- Failed tasks are properly recorded and don't break the synthesis process
- Each interface handles errors appropriately for its context

### Configuration Management

The `config.py` module provides:
- Dataclass-based configuration with type hints
- Environment variable loading with `.env` support
- Command-line argument integration
- Global configuration instance for easy access

### YAML Trace Format

Custom YAML dumper in `tracing/yaml_dumper.py` handles multiline strings and special characters properly, creating human-readable trace files for debugging.

## Testing and Development

### Module Testing

Each module can be tested independently:
```bash
# Test core functionality
python -c "from llm_pro_mode.core.processor import main; print('Core module loaded')"

# Test configuration
python -c "from llm_pro_mode.config import config; print(f'Config: {config.model_name}')"

# Test interfaces
python -c "from llm_pro_mode.interfaces.api import app; print('API module loaded')"
```

### Development Workflow

1. Install in development mode: `pip install -e .`
2. Make changes to specific modules
3. Test with: `llm-pro-mode --help`
4. Run in desired mode: CLI, TUI, or server