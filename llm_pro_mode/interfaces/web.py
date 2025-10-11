"""Web UI interface with WebSocket support for real-time task monitoring."""

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..config.runtime import RuntimeState
from ..models.schemas import (
    WebSocketMessage,
    TaskUpdate,
    CompletionRequest,
    ProfileListResponse,
    ProfileSummary,
    ProfileSelectRequest,
)
from ..core.processor import Processor, ProcessorHooks, RunContext, ProcessorResult
from ..core.llm_client import LLMChunk, LLMResult, normalize_content
from ..core.synthesizer import build_synthesis_prompt
from ..logger import get_logger
from ..tracing.logger import TraceLogger
from .runtime_context import RuntimeContext
from .support import SimpleStatsCollector, create_trace_logger
from .trace_endpoints import register_trace_endpoints


CancelledError = asyncio.CancelledError

_runtime_context = RuntimeContext("Web")
_logger = get_logger()


def configure_runtime(state: RuntimeState) -> None:
    _runtime_context.configure(state)


def _profile_api_key_preview(value: Optional[str]) -> Optional[str]:
    """Return a safe preview for API key values."""

    if not value:
        return None

    if value.isupper() and '_' in value and not value.startswith(('sk-', 'sk_', 'xai-', 'ant-')):
        # Likely an environment variable reference, safe to display as-is
        return value

    if len(value) <= 6:
        return value[:2] + "***"

    return f"{value[:4]}...{value[-2:]}"


class WebSocketManager:
    """Manages WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_tasks: Dict[str, str] = {}  # connection_id -> session_id
        self.active_jobs: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, connection_id: str):
        """Accept WebSocket connection."""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        _logger.debug(f"WebSocket connection established: {connection_id}")

    def disconnect(self, connection_id: str):
        """Remove WebSocket connection."""
        job = self.active_jobs.pop(connection_id, None)
        if job and not job.done():
            job.cancel()
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        if connection_id in self.connection_tasks:
            del self.connection_tasks[connection_id]
        _logger.debug(f"WebSocket connection closed: {connection_id}")

    def set_active_job(self, connection_id: str, job: Optional[asyncio.Task]):
        """Track the active job for a connection."""
        if job is None:
            self.active_jobs.pop(connection_id, None)
        else:
            self.active_jobs[connection_id] = job

    def cancel_active_job(self, connection_id: str):
        """Cancel the active job for a connection if running."""
        job = self.active_jobs.get(connection_id)
        if job and not job.done():
            job.cancel()

    async def send_message(self, connection_id: str, message: dict):
        """Send message to specific connection."""
        if connection_id in self.active_connections:
            try:
                await self.active_connections[connection_id].send_text(json.dumps(message))
            except Exception as e:
                _logger.warning(f"Error sending message to {connection_id}: {e}")
                self.disconnect(connection_id)

    async def broadcast_to_session(self, session_id: str, message: dict):
        """Broadcast message to all connections in a session."""
        for conn_id, websocket in list(self.active_connections.items()):
            if self.connection_tasks.get(conn_id) == session_id:
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    _logger.warning(f"Error broadcasting to {conn_id}: {e}")
                    self.disconnect(conn_id)


class WebSocketProgressTracker:
    """Tracks task progress and sends updates via WebSocket."""

    def __init__(self, manager: WebSocketManager, connection_id: str, session_id: str):
        self.manager = manager
        self.connection_id = connection_id
        self.session_id = session_id
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.stats_collector = SimpleStatsCollector()

    async def start_task(self, task_id: str, title: str, metadata: Optional[Dict] = None):
        """Start tracking a new task."""
        task_data = {
            "id": task_id,
            "title": title,
            "status": "running",
            "progress": 0,
            "thinking": "",
            "content": "",
            "metadata": metadata or {},
            "start_time": None
        }
        self.tasks[task_id] = task_data
        self.stats_collector.start_task(task_id)

        await self.manager.send_message(self.connection_id, {
            "type": "task_started",
            "task_id": task_id,
            "title": title,
            "metadata": metadata
        })

    async def update_task_progress(self, task_id: str, progress: float, thinking: str = "", content: str = ""):
        """Update task progress."""
        if task_id not in self.tasks:
            _logger.debug(f"Task {task_id} not found in tasks: {list(self.tasks.keys())}")
            return

        task = self.tasks[task_id]
        task["progress"] = progress
        normalized_thinking = normalize_content(thinking)
        normalized_content = normalize_content(content)

        if normalized_thinking:
            task["thinking"] += normalized_thinking
        if normalized_content:
            task["content"] += normalized_content

        await self.manager.send_message(self.connection_id, {
            "type": "task_progress",
            "task_id": task_id,
            "progress": progress,
            "thinking": normalized_thinking,
            "content": normalized_content
        })

    async def complete_task(
        self,
        task_id: str,
        success: bool = True,
        error: str = None,
        thinking: str = "",
        content: str = "",
        status: Optional[str] = None,
    ):
        """Mark task as completed."""
        if task_id not in self.tasks:
            return

        task = self.tasks[task_id]
        final_status = status or ("completed" if success else "failed")
        task["status"] = final_status
        task["progress"] = 100
        normalized_thinking = normalize_content(thinking)
        normalized_content = normalize_content(content)
        if normalized_thinking:
            task["thinking"] += normalized_thinking
        if normalized_content:
            task["content"] += normalized_content
        if error:
            task["error"] = error

        # Estimate token count from content length (rough approximation: 1 token ≈ 4 chars)
        estimated_tokens = len(task["content"]) // 4
        self.stats_collector.complete_task(
            task_id, success, estimated_tokens, status=final_status
        )

        await self.manager.send_message(self.connection_id, {
            "type": "task_completed",
            "task_id": task_id,
            "success": success,
            "error": error,
            "thinking": normalized_thinking,
            "content": normalized_content,
            "status": final_status,
        })

    async def start_synthesis(self):
        """Start synthesis phase."""
        # Create synthesis task in progress tracker
        await self.start_task("synthesis", "Synthesis", {"type": "synthesis"})

        # Also send synthesis started message
        await self.manager.send_message(self.connection_id, {
            "type": "synthesis_started"
        })

    async def complete_synthesis(
        self,
        success: bool = True,
        error: str = None,
        thinking: str = "",
        content: str = "",
        status: Optional[str] = None,
    ):
        """Complete synthesis phase."""
        # Update synthesis task if it exists
        if "synthesis" in self.tasks:
            task = self.tasks["synthesis"]
            final_status = status or ("completed" if success else "failed")
            task["status"] = final_status
            task["progress"] = 100
            normalized_thinking = normalize_content(thinking)
            normalized_content = normalize_content(content)
            if normalized_thinking:
                task["thinking"] += normalized_thinking
            if normalized_content:
                task["content"] += normalized_content
            if error:
                task["error"] = error

            # Estimate token count for synthesis
            estimated_tokens = len(task["content"]) // 4
            self.stats_collector.complete_task(
                "synthesis", success, estimated_tokens, status=final_status
            )
        else:
            final_status = status or ("completed" if success else "failed")

        await self.manager.send_message(self.connection_id, {
            "type": "synthesis_completed",
            "success": success,
            "error": error,
            "thinking": self.tasks.get("synthesis", {}).get("thinking", ""),
            "content": self.tasks.get("synthesis", {}).get("content", ""),
            "status": final_status,
        })

    async def send_final_result(self, content: str, stats: Optional[Dict] = None):
        """Send final result to client."""
        await self.manager.send_message(self.connection_id, {
            "type": "final_result",
            "content": content,
            "stats": stats
        })

    async def send_error(self, message: str):
        """Send error message to client."""
        await self.manager.send_message(self.connection_id, {
            "type": "error",
            "message": message
        })

    async def cancel_active_tasks(self, reason: str):
        """Mark all running tasks as cancelled."""
        running_tasks = [
            task_id for task_id, task in self.tasks.items() if task.get("status") == "running"
        ]
        for task_id in running_tasks:
            await self.complete_task(
                task_id,
                success=False,
                error=reason,
                status="cancelled",
            )

    async def send_cancellation(self, reason: str):
        """Notify the client that the session was cancelled."""
        await self.manager.send_message(self.connection_id, {
            "type": "task_cancelled",
            "reason": reason,
        })


class WebProcessorHooksAdapter:
    """Adapter that bridges processor hooks to WebSocket tracker events."""

    def __init__(self, tracker: WebSocketProgressTracker):
        self.tracker = tracker
        self._run_progress: Dict[str, float] = {}
        self._synthesis_progress: float = 0

    def make_hooks(self) -> ProcessorHooks:
        return ProcessorHooks(
            run_start=self.on_run_start,
            run_chunk=self.on_run_chunk,
            run_complete=self.on_run_complete,
            run_error=self.on_run_error,
            synthesis_start=self.on_synthesis_start,
            synthesis_chunk=self.on_synthesis_chunk,
            synthesis_complete=self.on_synthesis_complete,
            synthesis_error=self.on_synthesis_error,
            cancelled=self.on_cancelled,
        )

    def on_run_start(self, context: RunContext) -> None:
        self._run_progress[context.run_id] = 10.0
        asyncio.create_task(
            self.tracker.start_task(
                context.run_id,
                f"Run {context.index + 1}",
                {"run_index": context.index},
            )
        )
        asyncio.create_task(
            self.tracker.update_task_progress(context.run_id, 10.0)
        )

    def on_run_chunk(self, context: RunContext, chunk: LLMChunk) -> None:
        current = self._run_progress.get(context.run_id, 10.0)
        if chunk.kind == "thinking":
            current = min(60.0, current + 2.0)
            asyncio.create_task(
                self.tracker.update_task_progress(
                    context.run_id,
                    current,
                    thinking=chunk.text,
                )
            )
        else:
            current = min(95.0, current + 1.0)
            asyncio.create_task(
                self.tracker.update_task_progress(
                    context.run_id,
                    current,
                    content=chunk.text,
                )
            )
        self._run_progress[context.run_id] = current

    def on_run_complete(self, context: RunContext, result: LLMResult) -> None:
        self._run_progress.pop(context.run_id, None)
        asyncio.create_task(
            self.tracker.complete_task(
                context.run_id,
                success=True,
                thinking="",
                content=result.content,
                status="completed",
            )
        )

    def on_run_error(self, context: RunContext, exc: BaseException) -> None:
        self._run_progress.pop(context.run_id, None)
        asyncio.create_task(
            self.tracker.complete_task(
                context.run_id,
                success=False,
                error=str(exc),
                status="failed",
            )
        )

    def on_synthesis_start(self) -> None:
        self._synthesis_progress = 40.0
        asyncio.create_task(self.tracker.start_synthesis())

    def on_synthesis_chunk(self, chunk: LLMChunk) -> None:
        if chunk.kind == "thinking":
            self._synthesis_progress = max(self._synthesis_progress, 60.0)
            asyncio.create_task(
                self.tracker.update_task_progress(
                    "synthesis",
                    self._synthesis_progress,
                    thinking=chunk.text,
                )
            )
        else:
            self._synthesis_progress = max(self._synthesis_progress, 80.0)
            asyncio.create_task(
                self.tracker.update_task_progress(
                    "synthesis",
                    self._synthesis_progress,
                    content=chunk.text,
                )
            )

    def on_synthesis_complete(self, result: LLMResult) -> None:
        asyncio.create_task(
            self.tracker.complete_synthesis(
                success=True,
                content=result.content,
                status="completed",
            )
        )

    def on_synthesis_error(self, exc: BaseException) -> None:
        asyncio.create_task(
            self.tracker.complete_synthesis(
                success=False,
                error=str(exc),
                status="failed",
            )
        )

    def on_cancelled(self) -> None:
        asyncio.create_task(self.tracker.cancel_active_tasks("Cancelled"))
# Global WebSocket manager instance
ws_manager = WebSocketManager()


def create_web_app() -> FastAPI:
    """Create and configure the FastAPI web application."""
    app = FastAPI(title="LLM Pro Mode - Web Interface")

    # Get static files directory
    static_dir = Path(__file__).parent / "static"

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def build_profile_response() -> ProfileListResponse:
        """Aggregate profile metadata for API responses."""
        state = _runtime_context.require_state()
        manager = state.profile_manager

        config_file = manager.load_config()
        profiles = [
            ProfileSummary(
                name=name,
                description=profile.description,
                model_name=profile.model_name,
                api_base=profile.api_base,
                api_key_preview=_profile_api_key_preview(profile.api_key),
            )
            for name, profile in config_file.profiles.items()
        ]

        active_profile = state.active_profile_name()
        default_profile = config_file.default_profile or None

        return ProfileListResponse(
            profiles=profiles,
            active_profile=active_profile,
            default_profile=default_profile,
        )

    @app.get("/api/profiles", response_model=ProfileListResponse)
    async def get_profiles():
        """Return available profiles and current selection."""
        return build_profile_response()

    @app.post("/api/profiles/select", response_model=ProfileListResponse)
    async def select_profile(request: ProfileSelectRequest):
        """Apply a profile and optionally mark it as default."""
        state = _runtime_context.require_state()
        success = state.apply_profile(request.name, make_default=request.make_default)
        if not success:
            raise HTTPException(status_code=404, detail="Profile not found")

        return build_profile_response()

    @app.get("/", response_class=HTMLResponse)
    async def read_root():
        """Serve the main web interface."""
        index_path = static_dir / "index.html"
        return FileResponse(index_path)

    # Register shared trace management endpoints
    register_trace_endpoints(app, _runtime_context.get_config)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time communication."""
        connection_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        await ws_manager.connect(websocket, connection_id)
        ws_manager.connection_tasks[connection_id] = session_id
        current_job: Optional[asyncio.Task] = None

        try:
            while True:
                # Receive message from client
                data = await websocket.receive_text()
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "completion_request":
                    if current_job and not current_job.done():
                        await ws_manager.send_message(connection_id, {
                            "type": "error",
                            "message": "Previous task is still running. Please wait or cancel it.",
                            "error_code": "task_busy",
                        })
                        continue

                    current_job = asyncio.create_task(
                        handle_completion_request(connection_id, session_id, message["data"]),
                        name=f"llm-pro-session-{connection_id}",
                    )
                    ws_manager.set_active_job(connection_id, current_job)

                    def _finalize(task: asyncio.Task):
                        nonlocal current_job
                        ws_manager.set_active_job(connection_id, None)
                        current_job = None
                        try:
                            task.result()
                        except CancelledError:
                            pass
                        except Exception as exc:  # pragma: no cover - diagnostic logging only
                            _logger.error(f"WebSocket task error: {exc}")

                    current_job.add_done_callback(_finalize)

                elif msg_type == "cancel_request":
                    if current_job and not current_job.done():
                        ws_manager.cancel_active_job(connection_id)
                    else:
                        await ws_manager.send_message(connection_id, {
                            "type": "task_cancelled",
                            "reason": "No active task to cancel."
                        })

        except WebSocketDisconnect:
            ws_manager.disconnect(connection_id)
        except Exception as e:
            _logger.error(f"WebSocket error: {e}")
            await ws_manager.send_message(connection_id, {
                "type": "error",
                "message": f"Server error: {str(e)}"
            })
            ws_manager.disconnect(connection_id)
        finally:
            ws_manager.cancel_active_job(connection_id)

    return app


async def handle_completion_request(connection_id: str, session_id: str, request_data: dict):
    """Handle completion request with real-time progress tracking."""
    # Create progress tracker
    progress_tracker = WebSocketProgressTracker(ws_manager, connection_id, session_id)

    # Parse request
    prompt = request_data["prompt"]
    n_runs = request_data.get("n_runs", 3)
    enable_trace = request_data.get("enable_trace", False)
    trace_compact = request_data.get("trace_compact", True)

    trace_logger = create_trace_logger(
        _runtime_context.get_config(),
        enabled=enable_trace,
        compact_mode=trace_compact,
    )

    try:
        # Process with WebSocket progress tracking
        result = await process_main_with_websocket(
            prompt=prompt,
            n_runs=n_runs,
            progress_tracker=progress_tracker,
            trace_logger=trace_logger,
        )

        # Send final result with stats
        stats = None
        if trace_logger and trace_logger.enabled:
            # Save trace to file
            if trace_logger.traces:
                saved_path = trace_logger.save_traces()
                _logger.info(f"Trace saved to: {saved_path}")
                stats = trace_logger.get_stats()
        else:
            # Use basic stats collected during execution
            stats = progress_tracker.stats_collector.get_stats()

        await progress_tracker.send_final_result(result or "No result generated", stats)

    except CancelledError:
        reason = "Cancelled by user"
        await progress_tracker.cancel_active_tasks(reason)
        await progress_tracker.send_cancellation(reason)
    except Exception as e:
        _logger.error(f"Error processing completion request: {e}")
        await ws_manager.send_message(connection_id, {
            "type": "error",
            "message": f"Processing error: {str(e)}"
        })


async def process_main_with_websocket(
    prompt: str,
    n_runs: int,
    progress_tracker: WebSocketProgressTracker,
    trace_logger: Optional[TraceLogger] = None,
) -> str:
    """Process completion with WebSocket progress updates using the processor."""

    config = _runtime_context.get_config()
    hooks_adapter = WebProcessorHooksAdapter(progress_tracker)
    processor = Processor(config, hooks=hooks_adapter.make_hooks())

    try:
        result = await processor.run(
            prompt,
            n_runs=n_runs,
            trace_logger=trace_logger,
        )
    except Exception as exc:
        await progress_tracker.send_error(f"Processing error: {exc}")
        _logger.error("Web processing error: %s", exc)
        raise

    final_text = result.best_text() or ""

    if hooks_adapter._synthesis_progress == 0:
        await progress_tracker.start_synthesis()
        status = "cancelled" if result.interrupted else "completed"
        await progress_tracker.complete_synthesis(
            success=not result.interrupted,
            status=status,
            content=result.partial_text or final_text,
            error="Cancelled by user" if result.interrupted else None,
        )
    elif result.interrupted:
        await progress_tracker.complete_synthesis(
            success=False,
            status="cancelled",
            content=result.partial_text or final_text,
            error="Cancelled by user",
        )

    return final_text




async def synthesize_result_websocket(
    candidates: list,
    progress_tracker: WebSocketProgressTracker,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Synthesize multiple candidate results using WebSocket streaming."""
    config = _runtime_context.get_config()
    from ..core.llm_client import call_llm_streaming

    try:
        _logger.debug(f"Synthesis: Processing {len(candidates)} candidates")

        # Build synthesis prompts using shared function
        system_prompt, user_prompt = build_synthesis_prompt(candidates)

        # Start task trace
        task_trace = None
        if trace_logger and trace_id:
            task_trace = trace_logger.start_task(
                trace_id,
                config.model_name,
                user_prompt,
                {
                    "system": system_prompt,
                    "temperature": config.synthesis_temperature,
                },
            )

        _logger.debug("Synthesis: Starting streaming call")

        # Make streaming call for synthesis
        thinking_content = ""
        response_content = ""

        async for chunk_type, content in call_llm_streaming(
            user_prompt,
            temperature=config.synthesis_temperature,
            max_tokens=None,
            system=system_prompt,
            trace_logger=trace_logger,
            trace_id=trace_id,
            metadata={"phase": "synthesis"},
            config=config,
        ):
            normalized_content = normalize_content(content)

            if chunk_type == "thinking":
                thinking_content += normalized_content
                if trace_logger and task_trace and normalized_content:
                    trace_logger.log_thinking(task_trace, normalized_content)

                # Update synthesis task progress with thinking
                await progress_tracker.update_task_progress(
                    "synthesis", 50, thinking=normalized_content
                )

            elif chunk_type == "content":
                response_content += normalized_content
                if trace_logger and task_trace and normalized_content:
                    trace_logger.log_content(task_trace, normalized_content)

                # Update synthesis task progress with content
                await progress_tracker.update_task_progress(
                    "synthesis", 80, content=normalized_content
                )

            elif chunk_type == "error":
                _logger.warning(f"Synthesis error: {normalized_content}")
                # Don't re-raise, just handle gracefully
                # The error content will be empty, which is fine
                break

        _logger.debug(f"Synthesis: Completed with {len(response_content)} chars")

        # Complete task trace
        if trace_logger and task_trace:
            trace_logger.finish_task(task_trace, success=True)

        # Complete synthesis task with collected content
        await progress_tracker.complete_synthesis(
            success=True,
            thinking=thinking_content,
            content=response_content
        )

        return response_content

    except CancelledError:
        _logger.debug("Synthesis cancelled")
        if trace_logger and task_trace:
            trace_logger.finish_task(task_trace, success=False, error_msg="Cancelled")

        await progress_tracker.complete_synthesis(
            success=False,
            error="Cancelled by user",
            thinking=thinking_content,
            content=response_content,
            status="cancelled",
        )
        raise

    except Exception as e:
        _logger.error(f"Synthesis exception: {e}")
        if trace_logger and task_trace:
            trace_logger.finish_task(task_trace, success=False, error_msg=str(e))

        # Complete synthesis task with error
        await progress_tracker.complete_synthesis(
            success=False,
            error=str(e),
            thinking=thinking_content,
            content=response_content
        )
        raise


# Create the app instance
app = create_web_app()
