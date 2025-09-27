# LLM Pro Mode Desktop (Tauri)

Tauri shell that bundles the existing Web UI into a lightweight desktop application. The Rust side manages a local Python/uvicorn server and loads it inside a native window.

## Requirements
- Rust toolchain (edition 2021) with `cargo`
- `cargo install tauri-cli`
- Python 3 with the project dependencies installed (`pip install -e .` in repository root)

Set `LLM_PRO_PYTHON` if your interpreter is not available as `python3` (`python` on Windows is detected automatically):

```bash
export LLM_PRO_PYTHON="$HOME/.pyenv/versions/3.11.7/bin/python"
```

## Run in development
```bash
cd desktop
cargo tauri dev
```
The command launches the Python FastAPI backend on a free localhost port and then opens a Tauri window pointed at that port.

## Build distributables
```bash
cd desktop
cargo tauri build
```
The resulting installers/binaries will be placed under `src-tauri/target/release/bundle/`.

The backend process is terminated automatically when the app window closes or the Tauri runtime exits.
