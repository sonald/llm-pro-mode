"""Shared helpers for interface layers."""

from __future__ import annotations

from typing import Any, Dict, Optional

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

