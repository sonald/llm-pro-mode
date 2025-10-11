"""FastAPI server interface."""

from __future__ import annotations

from fastapi import FastAPI, Response

from ..config.runtime import RuntimeState
from ..core.processor import Processor
from ..logger import get_logger
from ..models.schemas import Request
from ..tracing.logger import TraceLogger


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

    trace_logger: TraceLogger | None = None
    if request.enable_trace:
        trace_logger = TraceLogger(
            trace_dir=config.trace_dir,
            enabled=True,
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

        if request.enable_trace and trace_logger and trace_logger.traces:
            stats = trace_logger.get_stats()
            trace_info = f"\n\n<!-- Debug Info: {stats} -->"
            content += trace_info

        return Response(content=content, media_type="text/markdown")
    except Exception as exc:  # pragma: no cover - defensive
        _logger.error("API completion error: %s", exc)
        return Response(content=f"Error: {exc}", status_code=500)