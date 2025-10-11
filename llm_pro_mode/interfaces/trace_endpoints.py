"""Shared trace API endpoints for REST interfaces."""

from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from ..config import Config
from ..logger import get_logger
from .support import delete_trace_file, list_trace_metadata, load_trace_content


_logger = get_logger()


def register_trace_endpoints(app: FastAPI, get_config: Callable[[], Config]) -> None:
    """Register trace management endpoints on a FastAPI app.

    Args:
        app: FastAPI application instance
        get_config: Callable that returns the current Config instance
    """

    @app.get("/api/traces")
    async def list_traces():
        """List all trace files with metadata."""
        config = get_config()
        traces = list_trace_metadata(config, logger=_logger)
        return JSONResponse(content={"traces": traces})

    @app.get("/api/traces/{filename}")
    async def get_trace(filename: str):
        """Get specific trace file content."""
        config = get_config()
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
        config = get_config()
        try:
            delete_trace_file(config, filename, logger=_logger)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Trace file not found")
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Failed to delete trace: {exc}")

        return JSONResponse(content={"success": True, "message": "Trace deleted"})
