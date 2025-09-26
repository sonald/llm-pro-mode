"""FastAPI server interface."""

from fastapi import FastAPI, Response

from ..models.schemas import Request
from ..core.processor import main
from ..tracing.logger import TraceLogger


app = FastAPI()


@app.post("/completion")
async def completion(request: Request):
    """API endpoint for LLM completion requests."""
    # Create trace logger if enabled
    trace_logger = None
    if request.enable_trace:
        trace_logger = TraceLogger(
            enabled=True,
            compact_mode=request.trace_compact,
        )

    try:
        prompt = request.prompt
        n_runs = request.n_runs
        res = await main(prompt, n_runs, trace_logger=trace_logger)

        # If trace logging is enabled, return additional debug information
        if request.enable_trace and trace_logger and trace_logger.traces:
            stats = trace_logger.get_stats()
            trace_info = f"\n\n<!-- Debug Info: {stats} -->"
            res += trace_info

        return Response(content=res, media_type="text/markdown")
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)