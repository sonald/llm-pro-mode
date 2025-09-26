"""LLM call trace logger for debugging and analysis."""

import uuid
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .yaml_dumper import CustomYAMLDumper


class TraceLogger:
    """LLM call trace recorder for debugging and analysis."""

    def __init__(
        self,
        trace_dir: str = "traces",
        enabled: bool = True,
        compact_mode: bool = False,
    ):
        """
        Initialize trace logger.

        Args:
            trace_dir: Directory to save trace files
            enabled: Whether to enable trace logging
            compact_mode: Whether to use simplified mode (only save key info)
        """
        self.enabled = enabled
        self.compact_mode = compact_mode
        self.trace_dir = Path(trace_dir)
        self.traces: List[Dict[str, Any]] = []
        self.session_id = str(uuid.uuid4())[:8]

        # Create trace directory
        if self.enabled:
            self.trace_dir.mkdir(exist_ok=True)

    def start_task(
        self,
        task_id: str,
        model_name: str,
        input_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start a new task trace.

        Args:
            task_id: Unique task identifier
            model_name: Model name being used
            input_prompt: Input prompt
            metadata: Additional metadata

        Returns:
            Task trace object
        """
        if not self.enabled:
            return {}

        task_trace = {
            "task_id": task_id,
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "model": model_name,
            "input": {"prompt": input_prompt, "metadata": metadata or {}},
            "thinking": "",
            "content": "",
            "output": {"total_tokens": 0, "thinking_tokens": 0, "content_tokens": 0},
            "status": "started",
            "duration_ms": 0,
            "error": None,
        }

        return task_trace

    def log_thinking(self, task_trace: Dict[str, Any], thinking_content: str):
        """Log thinking process."""
        if not self.enabled or not task_trace:
            return

        task_trace["thinking"] += thinking_content
        task_trace["output"]["thinking_tokens"] += len(thinking_content)

    def log_content(self, task_trace: Dict[str, Any], content: str):
        """Log output content."""
        if not self.enabled or not task_trace:
            return

        task_trace["content"] += content
        task_trace["output"]["content_tokens"] += len(content)

    def finish_task(
        self,
        task_trace: Dict[str, Any],
        success: bool = True,
        error_msg: Optional[str] = None,
    ):
        """
        Complete task trace.

        Args:
            task_trace: Task trace object
            success: Whether completed successfully
            error_msg: Error message if any
        """
        if not self.enabled or not task_trace:
            return

        # Calculate duration
        start_time = datetime.fromisoformat(task_trace["timestamp"])
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Update task status
        task_trace.update(
            {
                "status": "completed" if success else "failed",
                "duration_ms": duration_ms,
                "completed_at": end_time.isoformat(),
                "error": error_msg,
                "output": {
                    **task_trace["output"],
                    "total_tokens": task_trace["output"]["thinking_tokens"]
                    + task_trace["output"]["content_tokens"],
                },
            }
        )

        # Choose data to save based on mode
        if self.compact_mode:
            # Simplified mode: only save key info, no token statistics
            compact_trace = {
                "task_id": task_trace["task_id"],
                "model": task_trace["model"],
                "input": task_trace["input"]["prompt"],  # Save prompt string directly
                "thinking": task_trace["thinking"],
                "content": task_trace["content"],
                "error": task_trace["error"],
                "status": task_trace["status"],
                "duration_ms": task_trace["duration_ms"],
                # Note: no token statistics included
            }
            self.traces.append(compact_trace)
        else:
            # Full mode: save all information
            self.traces.append(task_trace)

        # Auto-save (every 10 tasks)
        if len(self.traces) % 10 == 0:
            self.save_traces()

    def save_traces(self, filename: Optional[str] = None) -> str:
        """
        Save traces to YAML file.

        Args:
            filename: Filename, auto-generated if not specified

        Returns:
            Saved file path
        """
        if not self.enabled:
            return ""

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"trace_{self.session_id}_{timestamp}.yaml"

        filepath = self.trace_dir / filename

        # Prepare data to save
        save_data = {
            "session_info": {
                "session_id": self.session_id,
                "created_at": datetime.now().isoformat(),
                "total_tasks": len(self.traces),
                "mode": "compact" if self.compact_mode else "full",
            },
            "traces": self.traces,
        }

        # Save as YAML format, using custom dumper for multiline strings
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                save_data,
                f,
                Dumper=CustomYAMLDumper,
                default_flow_style=False,
                allow_unicode=True,
                width=1000,  # Increase line width to avoid auto line breaks
                indent=2,
            )

        return str(filepath)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for current session."""
        if not self.traces:
            return {}

        total_tasks = len(self.traces)
        successful_tasks = len([t for t in self.traces if t["status"] == "completed"])

        # Calculate token statistics based on mode
        if self.compact_mode:
            # Compact mode: no token information
            total_tokens = 0
        else:
            # Full mode: calculate total tokens
            total_tokens = sum(
                t.get("output", {}).get("total_tokens", 0) for t in self.traces
            )

        avg_duration = (
            sum(t.get("duration_ms", 0) for t in self.traces) / total_tasks
            if total_tasks > 0
            else 0
        )

        return {
            "session_id": self.session_id,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "success_rate": successful_tasks / total_tasks if total_tasks > 0 else 0,
            "total_tokens": total_tokens,
            "avg_duration_ms": avg_duration,
            "mode": "compact" if self.compact_mode else "full",
        }