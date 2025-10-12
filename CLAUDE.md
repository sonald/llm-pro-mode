# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM Pro Mode is a modular Python application providing **four interface modes** (CLI, TUI, Web UI, and Desktop) for parallel LLM completions with result synthesis. The architecture emphasizes clean separation of concerns, structured concurrency, and flexible configuration.

## Architecture

### Package Structure

```
llm_pro_mode/
├── main.py                  # Entry point and CLI argument parsing
├── config/                  # Configuration system
│   ├── __init__.py          # Core Config dataclass
│   └── runtime.py           # RuntimeState and ConfigLoader
├── profile_manager.py       # JSON profile configuration
├── core/                    # Business logic
│   ├── llm_client.py        # LLM API calls and streaming
│   ├── synthesizer.py       # Result synthesis
│   └── processor.py         # Parallel execution coordination
├── interfaces/              # UI implementations
│   ├── cli.py              # Command-line interface
│   ├── tui.py              # Terminal UI (Textual)
│   ├── web.py              # Web UI (FastAPI + WebSocket)
│   ├── api.py              # RESTful API server
│   ├── support.py          # Shared interface utilities
│   └── static/             # Web UI assets (HTML/CSS/JS)
├── tracing/                # Debug logging
│   ├── logger.py           # TraceLogger for debugging
│   └── yaml_dumper.py      # YAML serialization
├── models/                 # Data models
│   └── schemas.py          # Pydantic models
└── utils/                  # Utilities
    └── tokens.py           # Token counting
```

### Key Design Patterns

**RuntimeState and ConfigLoader**: Configuration assembly happens in `config/runtime.py` using `RuntimeState` (holds config + profile manager) and `ConfigLoader` (builds state from CLI args + environment + profiles). This pattern enables dependency injection and testability.

**Processor with Hooks**: `core/processor.py` uses `ProcessorHooks` dataclass for progress callbacks, enabling different interfaces to track parallel execution without tight coupling.

**Multi-Interface Architecture**: Four modes share core logic:
- **CLI** (`--prompt`): Rich progress bars, stdout output
- **TUI** (`--tui`): Textual-based interactive terminal
- **Web UI** (`--web`): Modern web interface with WebSocket streaming
- **API Server** (`--serve`): RESTful endpoints for integration

**Parallel Processing**: Uses `anyio.create_task_group()` for structured concurrency - spawns N parallel LLM calls, collects results, then synthesizes using a separate call with different temperature.

## Development Commands

### Installation

```bash
# Development installation (editable mode)
pip install -e .

# Verify installation
llm-pro-mode --help
```

**Note on Package Structure**: The project uses explicit package discovery in `pyproject.toml` to only include the `llm_pro_mode` package. The `desktop/`, `traces/`, and `docs/` directories are excluded from the Python package to avoid conflicts during installation.

### Running the Application

**CLI Mode**:
```bash
llm-pro-mode --prompt "Your prompt" --model "gpt-4"
llm-pro-mode -p "Question" -m "claude-3-sonnet" -n 5
llm-pro-mode -p - < input.txt  # stdin support
```

**TUI Mode** (interactive terminal):
```bash
llm-pro-mode --tui
llm-pro-mode --tui --n_runs 5 --trace
```

**Web UI Mode** (ChatGPT-style interface):
```bash
llm-pro-mode --web --port 8000
# Open browser to http://localhost:8000
```

**API Server Mode** (RESTful endpoints):
```bash
llm-pro-mode --serve --port 8080
```

**Desktop App** (Tauri wrapper):
```bash
cd desktop
cargo tauri dev      # Development mode
cargo tauri build    # Production build
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_integration.py

# Run with verbose output
pytest -v

# Run async tests
pytest tests/test_llm_streaming.py
```

### Profile Management

Configuration priority: CLI args > JSON profiles > Environment variables > Defaults

```bash
# Profile operations
llm-pro-mode --list-profiles
llm-pro-mode --show-profile openai
llm-pro-mode --save-profile my-config --model "gpt-4" --api_base "https://api.openai.com/v1"
llm-pro-mode --set-default-profile openai
llm-pro-mode --delete-profile old-config

# Use profile
llm-pro-mode --profile grok --prompt "Question"
```

**Config file locations** (checked in order):
1. `./llm_pro_config.json`
2. `~/.llm-pro-mode/config.json`
3. `./config.json`

### Debug Tracing

```bash
# Enable trace logging
llm-pro-mode --trace --prompt "test"

# Compact trace mode
llm-pro-mode --trace --trace_compact --prompt "test"

# Custom trace directory
llm-pro-mode --trace --trace_dir ./debug_traces --prompt "test"
```

### Syntax Checking

```bash
# Check Python syntax
python -m compileall llm_pro_mode

# Type checking (if mypy installed)
mypy llm_pro_mode
```

## Configuration System

### Environment Variables

```bash
export LLM_PRO_MODEL="gpt-4"
export LLM_PRO_API_BASE="https://api.openai.com/v1"
export LLM_PRO_API_KEY="sk-..."

# Sampling parameters
export LLM_PRO_TEMPERATURE=0.8
export LLM_PRO_SYNTH_TEMPERATURE=0.3
export LLM_PRO_MAX_TOKENS=1200

# Desktop app Python interpreter
export LLM_PRO_PYTHON="$HOME/.pyenv/versions/3.11.7/bin/python"
```

### API Key Resolution

Profile `api_key` fields support environment variable names:
```json
{
  "profiles": {
    "openai": {
      "api_key": "OPENAI_API_KEY",  // Resolved from env at runtime
      "model_name": "gpt-4",
      "api_base": "https://api.openai.com/v1"
    }
  }
}
```

### Command-Line Parameters

```bash
--model, -m          # Model name
--api_base, -b       # API base URL
--api_key, -k        # API key or env var name
--prompt, -p         # Input prompt (or '-' for stdin)
--n_runs, -n         # Parallel runs (default: 3)
--temperature        # Sampling temperature
--synthesis_temperature  # Temperature for synthesis step
--max_tokens         # Max tokens per request
--profile            # Profile name to use
--port, -P           # Server/Web UI port
--serve              # API server mode
--web                # Web UI mode
--tui                # Terminal UI mode
--trace, -t          # Enable trace logging
--trace_dir          # Trace output directory
--trace_compact, --tc  # Compact trace format
```

## Code Architecture Details

### Configuration Assembly (`config/runtime.py`)

**RuntimeState**: Holds `Config` + `ProfileManager` + API key source tracking. Provides methods for profile operations, environment application, and CLI override merging.

**ConfigLoader**: Orchestrates configuration loading:
1. Load `.env` file
2. Initialize ProfileManager
3. Create RuntimeState
4. Apply profile (requested or default)
5. Apply environment variables
6. Apply CLI argument overrides

### Parallel Execution (`core/processor.py`)

**Processor.run()** workflow:
1. Create task group with `anyio.create_task_group()`
2. Spawn N parallel `_execute_single_run()` tasks
3. Collect results via shared `run_outputs` list
4. Handle interruption (Ctrl+C) gracefully
5. If multiple successful results, call `_run_synthesis()`
6. Return `ProcessorResult` with final/partial text

**ProcessorHooks**: Optional callbacks for progress tracking:
- `run_start`, `run_chunk`, `run_complete`, `run_error`
- `synthesis_start`, `synthesis_chunk`, `synthesis_complete`, `synthesis_error`
- `cancelled`

### Interface Integration

**CLI** (`interfaces/cli.py`): Rich progress bars, synchronous wrapper, stdout output

**TUI** (`interfaces/tui.py`): Textual widgets, reactive UI, Emacs-style keybindings

**Web UI** (`interfaces/web.py`): FastAPI + WebSocket, real-time task monitoring, ChatGPT-style interface with streaming

**API** (`interfaces/api.py`): RESTful `/completion` endpoint, trace file management endpoints

### WebSocket Protocol (Web UI)

Message types:
- `task_started`: Parallel run begins
- `task_progress`: Chunk received (with thinking/content/progress%)
- `task_completed`: Run finished
- `synthesis_started`: Synthesis begins
- `synthesis_chunk`: Synthesis streaming
- `synthesis_complete`: Synthesis done
- `final_result`: Complete response
- `error`: Error occurred

### Trace Logging

**TraceLogger** (`tracing/logger.py`): Optional debug logger that captures:
- Request/response pairs
- Streaming chunks
- Token counts and timing
- Run-level and synthesis-level traces

**YAML Output** (`tracing/yaml_dumper.py`): Custom YAML serialization handling multiline strings and special characters for human-readable trace files.

## Desktop Application Architecture (Tauri + Rust)

### Rust Backend (`desktop/src-tauri/src/lib.rs`)

The Tauri desktop wrapper provides native window management and Python backend lifecycle:

**Key Components**:
- `spawn_backend()`: Launches Python FastAPI server as child process with proper `PYTHONPATH` configuration
- `wait_for_server()`: Polls TCP connection until backend is ready (15 second timeout)
- `shutdown_backend()`: Cleanly terminates Python process on app exit
- `project_root()`: Resolves project directory at build time for reliable path resolution

**Python Interpreter Selection**:
1. Check `LLM_PRO_PYTHON` environment variable (highest priority)
2. Fall back to `python3` (Unix) or `python` (Windows)
3. Set `PYTHONPATH` to project root so Python can import `llm_pro_mode`

**macOS-Specific Focus Management**:
- Uses `cocoa` and `objc` crates for NSApp API access
- `force_activate()`: Calls `NSApp().activateIgnoringOtherApps_(YES)` to bring app to foreground
- Window activation sequence in `RunEvent::Ready` (not `setup()`):
  1. Force activate app (macOS App level)
  2. Show window (macOS Key Window level)
  3. Set focus (macOS First Responder level)
- Window initially `visible: false` in `tauri.conf.json` to avoid WebKit navigation timing issues

### Desktop Application (Tauri)

Located in `desktop/` directory. Tauri app automatically:
- Starts FastAPI backend on random available port
- Opens native window with embedded Web UI
- Terminates backend process on app close

**Prerequisites**:
- Rust (2021 edition)
- `cargo` and `tauri-cli`
- Python environment with llm-pro-mode installed: `pip install -e .`
- Python accessible via `python3` or `LLM_PRO_PYTHON` environment variable

**Important**: If you have multiple Python environments (virtualenv, conda, pyenv), you MUST set `LLM_PRO_PYTHON`:

```bash
# Find which Python has llm-pro-mode installed
python3 -m pip show llm-pro-mode | grep Location

# Set the correct Python interpreter
export LLM_PRO_PYTHON=/path/to/your/python3
# Example: export LLM_PRO_PYTHON=$HOME/miniforge3/bin/python3
```

**Development**:
```bash
# First time setup
pip install -e .  # Install package in editable mode

# Start desktop app
cd desktop
cargo tauri dev
```

**Production Build**:
```bash
cd desktop
cargo tauri build
# Outputs in desktop/src-tauri/target/release/bundle/
```

**Common Desktop Issues**:

1. **`ModuleNotFoundError: No module named 'uvicorn'`**
   - Cause: Tauri using wrong Python interpreter
   - Fix: Set `LLM_PRO_PYTHON` to the Python where you ran `pip install -e .`

2. **`Backend server failed to start in time`**
   - Cause: Missing dependencies or port conflict
   - Fix: Test backend manually: `python3 -m llm_pro_mode.desktop --port 8000`

3. **macOS keyboard focus issue** (already fixed in main)
   - The desktop app uses `activateIgnoringOtherApps_(YES)` via cocoa FFI
   - Window activation happens in `RunEvent::Ready` for proper timing
   - See `docs/MACOS_FOCUS_FIX.md` for technical details

## Common Development Tasks

### Adding a New Interface Mode

1. Create new file in `interfaces/`
2. Implement `ProcessorHooks` for progress tracking
3. Initialize `Processor` with hooks
4. Call `processor.run()` with prompt and config
5. Add mode flag to `main.py` argument parser
6. Add conditional in `main.py` to launch new interface

### Modifying Parallel Execution Logic

Edit `core/processor.py`:
- `Processor._execute_single_run()`: Individual run logic
- `Processor._run_synthesis()`: Synthesis step
- `ProcessorHooks`: Add new callback types

### Adding Configuration Options

1. Add field to `Config` dataclass in `config/__init__.py`
2. Add environment variable parsing in `RuntimeState.apply_environment()`
3. Add CLI argument in `main.py`
4. Add override in `RuntimeState.apply_overrides_from_args()`
5. Update profile schema in `profile_manager.py` if needed

### Extending Web UI

Edit files in `interfaces/static/`:
- `index.html`: Layout and structure
- `style.css`: Styling and themes
- `app.js`: WebSocket client and UI logic

Add WebSocket message types in `interfaces/web.py` and `models/schemas.py`.

## Testing Strategy

- **Unit tests**: Individual modules (`test_llm_client_core.py`)
- **Integration tests**: End-to-end flows (`test_integration.py`)
- **Streaming tests**: Async stream handling (`test_llm_streaming.py`)
- **WebSocket tests**: Real-time communication (`test_websocket_manager.py`)

Uses `pytest` with `pytest-asyncio` for async test support.
