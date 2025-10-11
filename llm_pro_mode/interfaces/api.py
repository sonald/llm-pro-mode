"""FastAPI server interface."""

from __future__ import annotations

import yaml
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import JSONResponse

from ..config.runtime import RuntimeState
from ..core.processor import Processor
from ..logger import get_logger
from ..models.schemas import Request
from .support import create_trace_logger


app = FastAPI()
_runtime_state: RuntimeState | None = None
_logger = get_logger()


def configure_runtime(state: RuntimeState) -> None:
    global _runtime_state
    _runtime_state = state


def _require_state() -> RuntimeState:
    if _runtime_state is None:
        raise RuntimeError("API runtime state not configured")
    return _runtime_state


@app.post("/completion")
async def completion(request: Request):
    """API endpoint for LLM completion requests."""
    state = _require_state()
    config = state.config

    trace_logger = create_trace_logger(
        config,
        enabled=request.enable_trace,
        compact_mode=request.trace_compact,
    )

    try:
        processor = Processor(config)
        result = await processor.run(
            request.prompt,
            n_runs=request.n_runs,
            trace_logger=trace_logger,
        )

        content = result.best_text() or ""

        if trace_logger and trace_logger.traces:
            stats = trace_logger.get_stats()
            trace_info = f"\n\n<!-- Debug Info: {stats} -->"
            content += trace_info

        return Response(content=content, media_type="text/markdown")
    except Exception as exc:  # pragma: no cover - defensive
        _logger.error("API completion error: %s", exc)
        return Response(content=f"Error: {exc}", status_code=500)


@app.get("/api/traces")
async def list_traces():
    """List all trace files with metadata."""
    state = _require_state()
    config = state.config
    trace_dir = Path(config.trace_dir)

    if not trace_dir.exists():
        return JSONResponse(content={"traces": []})

    traces = []
    for trace_file in sorted(trace_dir.glob("trace_*.yaml"), reverse=True):
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            session_info = data.get("session_info", {})
            trace_list = data.get("traces", [])

            # Calculate statistics
            total_tasks = len(trace_list)
            completed = sum(1 for t in trace_list if t.get("status") == "completed")
            failed = sum(1 for t in trace_list if t.get("status") == "failed")
            total_tokens = sum(
                t.get("output", {}).get("total_tokens", 0) for t in trace_list
            )

            traces.append(
                {
                    "filename": trace_file.name,
                    "session_id": session_info.get("session_id", "unknown"),
                    "created_at": session_info.get("created_at", ""),
                    "mode": session_info.get("mode", "full"),
                    "total_tasks": total_tasks,
                    "completed_tasks": completed,
                    "failed_tasks": failed,
                    "total_tokens": total_tokens,
                    "size_bytes": trace_file.stat().st_size,
                }
            )
        except Exception as exc:  # pragma: no cover
            _logger.error("Failed to read trace file %s: %s", trace_file.name, exc)
            continue

    return JSONResponse(content={"traces": traces})


@app.get("/api/traces/{filename}")
async def get_trace(filename: str):
    """Get specific trace file content."""
    state = _require_state()
    config = state.config
    trace_dir = Path(config.trace_dir)
    trace_file = trace_dir / filename

    # Security check: prevent path traversal
    if not trace_file.is_relative_to(trace_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not trace_file.exists():
        raise HTTPException(status_code=404, detail="Trace file not found")

    try:
        with open(trace_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return JSONResponse(content=data)
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to read trace file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read trace: {exc}")


@app.delete("/api/traces/{filename}")
async def delete_trace(filename: str):
    """Delete a specific trace file."""
    state = _require_state()
    config = state.config
    trace_dir = Path(config.trace_dir)
    trace_file = trace_dir / filename

    # Security check: prevent path traversal
    if not trace_file.is_relative_to(trace_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not trace_file.exists():
        raise HTTPException(status_code=404, detail="Trace file not found")

    try:
        trace_file.unlink()
        return JSONResponse(content={"success": True, "message": "Trace deleted"})
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to delete trace file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to delete trace: {exc}")
