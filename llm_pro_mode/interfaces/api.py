"""FastAPI server interface."""

from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from ..config.runtime import RuntimeState
from ..core.processor import Processor
from ..logger import get_logger
from ..models.schemas import Request
from .runtime_context import RuntimeContext
from .support import create_trace_logger
from .trace_endpoints import register_trace_endpoints


app = FastAPI()
_runtime_context = RuntimeContext("API")
_logger = get_logger()


def configure_runtime(state: RuntimeState) -> None:
    _runtime_context.configure(state)


@app.post("/completion")
async def completion(request: Request):
    """API endpoint for LLM completion requests."""
    config = _runtime_context.get_config()

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


# Register shared trace management endpoints
register_trace_endpoints(app, _runtime_context.get_config)
