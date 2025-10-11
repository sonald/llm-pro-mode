"""Shared helpers for interface layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..config import Config
from ..tracing.logger import TraceLogger


def create_trace_logger(
    config: Config,
    *,
    enabled: bool,
    compact_mode: bool,
) -> Optional[TraceLogger]:
    """Create a trace logger when tracing is enabled."""
    if not enabled:
        return None

    return TraceLogger(
        trace_dir=config.trace_dir,
        enabled=True,
        compact_mode=compact_mode,
    )


class SimpleStatsCollector:
    """Collects basic statistics without full tracing."""

    def __init__(self):
        self.total_tasks = 0
        self.completed_tasks = 0
        self.cancelled_tasks = 0
        self.total_tokens = 0
        self.total_duration_ms = 0
        self.start_times: Dict[str, float] = {}

    def start_task(self, task_id: str):
        import time

        self.total_tasks += 1
        self.start_times[task_id] = time.time() * 1000

    def complete_task(
        self,
        task_id: str,
        success: bool = True,
        token_count: int = 0,
        status: Optional[str] = None,
    ):
        import time

        final_status = status or ("completed" if success else "failed")
        if final_status == "completed":
            self.completed_tasks += 1
        elif final_status == "cancelled":
            self.cancelled_tasks += 1
        self.total_tokens += token_count

        if task_id in self.start_times:
            duration = time.time() * 1000 - self.start_times[task_id]
            self.total_duration_ms += duration
            del self.start_times[task_id]

    def get_stats(self) -> Dict[str, Any]:
        avg_duration = self.total_duration_ms / max(1, self.completed_tasks)
        effective_total = self.total_tasks - self.cancelled_tasks
        success_rate = self.completed_tasks / max(1, effective_total)

        return {
            "total_tasks": self.total_tasks,
            "total_tokens": self.total_tokens,
            "avg_duration_ms": avg_duration,
            "success_rate": success_rate,
        }


def list_trace_metadata(
    config: Config,
    *,
    logger: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Aggregate metadata for available trace files."""

    trace_dir = Path(config.trace_dir)
    if not trace_dir.exists():
        return []

    traces: List[Dict[str, Any]] = []
    for trace_file in sorted(trace_dir.glob("trace_*.yaml"), reverse=True):
        try:
            with trace_file.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}

            session_info = data.get("session_info", {})
            trace_list = data.get("traces", [])

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
        except Exception as exc:  # pragma: no cover - defensive
            if logger is not None:
                logger.error("Failed to read trace file %s: %s", trace_file.name, exc)
            continue

    return traces


def load_trace_content(
    config: Config,
    filename: str,
    *,
    logger: Optional[Any] = None,
) -> Dict[str, Any]:
    """Return the parsed YAML content for a specific trace file."""

    trace_file = _resolve_trace_path(config, filename)
    if not trace_file.exists():
        raise FileNotFoundError(filename)

    try:
        with trace_file.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # pragma: no cover - defensive
        if logger is not None:
            logger.error("Failed to read trace file %s: %s", filename, exc)
        raise


def delete_trace_file(
    config: Config,
    filename: str,
    *,
    logger: Optional[Any] = None,
) -> None:
    """Delete a trace file if it exists."""

    trace_file = _resolve_trace_path(config, filename)
    if not trace_file.exists():
        raise FileNotFoundError(filename)

    try:
        trace_file.unlink()
    except Exception as exc:  # pragma: no cover - defensive
        if logger is not None:
            logger.error("Failed to delete trace file %s: %s", filename, exc)
        raise


def _resolve_trace_path(config: Config, filename: str) -> Path:
    trace_dir = Path(config.trace_dir).resolve()
    target = (trace_dir / filename).resolve()
    if not str(target).startswith(str(trace_dir)):
        raise ValueError("Invalid filename")
    return target
