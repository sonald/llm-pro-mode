"""FastAPI server interface."""

from __future__ import annotations

from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import JSONResponse

from ..config.runtime import RuntimeState
from ..core.processor import Processor
from ..logger import get_logger
from ..models.schemas import Request
from .support import (
    create_trace_logger,
    delete_trace_file,
    list_trace_metadata,
    load_trace_content,
)


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
    traces = list_trace_metadata(config, logger=_logger)
    return JSONResponse(content={"traces": traces})


@app.get("/api/traces/{filename}")
async def get_trace(filename: str):
    """Get specific trace file content."""
    config = _require_state().config
    try:
        data = load_trace_content(config, filename, logger=_logger)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Trace file not found")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to read trace: {exc}")

    return JSONResponse(content=data)


@app.delete("/api/traces/{filename}")
async def delete_trace(filename: str):
    """Delete a specific trace file."""
    config = _require_state().config
    try:
        delete_trace_file(config, filename, logger=_logger)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Trace file not found")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to delete trace: {exc}")

    return JSONResponse(content={"success": True, "message": "Trace deleted"})
