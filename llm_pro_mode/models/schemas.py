"""Pydantic models and data schemas."""

from pydantic import BaseModel


class Request(BaseModel):
    """Request model for API endpoints."""

    prompt: str
    n_runs: int = 3
    enable_trace: bool = False
    trace_compact: bool = False