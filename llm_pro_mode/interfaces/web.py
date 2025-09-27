"""Web UI interface with WebSocket support for real-time task monitoring."""

import asyncio
import json
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import config
from ..models.schemas import (
    WebSocketMessage,
    TaskUpdate,
    CompletionRequest,
    ProfileListResponse,
    ProfileSummary,
    ProfileSelectRequest,
)
from ..core.processor import main as process_main
from ..tracing.logger import TraceLogger


CancelledError = asyncio.CancelledError


def _normalize_stream_content(value) -> str:
    """Convert streamed reasoning/content payloads to plain text."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_normalize_stream_content(item) for item in value if item is not None)
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                candidate = _normalize_stream_content(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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
        print(f"WebSocket connection established: {connection_id}")

    def disconnect(self, connection_id: str):
        """Remove WebSocket connection."""
        job = self.active_jobs.pop(connection_id, None)
        if job and not job.done():
            job.cancel()
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        if connection_id in self.connection_tasks:
            del self.connection_tasks[connection_id]
        print(f"WebSocket connection closed: {connection_id}")

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
                print(f"Error sending message to {connection_id}: {e}")
                self.disconnect(connection_id)

    async def broadcast_to_session(self, session_id: str, message: dict):
        """Broadcast message to all connections in a session."""
        for conn_id, websocket in list(self.active_connections.items()):
            if self.connection_tasks.get(conn_id) == session_id:
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    print(f"Error broadcasting to {conn_id}: {e}")
                    self.disconnect(conn_id)


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
            "success_rate": success_rate
        }


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
            print(f"[DEBUG] Task {task_id} not found in tasks: {list(self.tasks.keys())}")
            return

        task = self.tasks[task_id]
        task["progress"] = progress
        normalized_thinking = _normalize_stream_content(thinking)
        normalized_content = _normalize_stream_content(content)

        if normalized_thinking:
            task["thinking"] += normalized_thinking
        if normalized_content:
            task["content"] += normalized_content

        # Debug logging for synthesis task
        if task_id == "synthesis":
            print(f"[DEBUG] Synthesis task update - progress: {progress}, thinking_len: {len(normalized_thinking)}, content_len: {len(normalized_content)}")
            print(f"[DEBUG] Synthesis task total - thinking_len: {len(task['thinking'])}, content_len: {len(task['content'])}")

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
        normalized_thinking = _normalize_stream_content(thinking)
        normalized_content = _normalize_stream_content(content)
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
            normalized_thinking = _normalize_stream_content(thinking)
            normalized_content = _normalize_stream_content(content)
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

        if not config.profile_manager:
            return ProfileListResponse(
                profiles=[],
                active_profile=None,
                default_profile=None,
            )

        config_file = config.profile_manager.load_config()
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

        active_profile = config.get_active_profile_name()
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

        if not config.profile_manager:
            raise HTTPException(status_code=400, detail="Profile management not configured")

        success = config.apply_profile(request.name, make_default=request.make_default)
        if not success:
            raise HTTPException(status_code=404, detail="Profile not found")

        return build_profile_response()

    @app.get("/", response_class=HTMLResponse)
    async def read_root():
        """Serve the main web interface."""
        index_path = static_dir / "index.html"
        return FileResponse(index_path)

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
                            "message": "Previous task is still running. Please wait or cancel it."
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
                            print(f"WebSocket task error: {exc}")

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
            print(f"WebSocket error: {e}")
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

    # Create trace logger if enabled
    trace_logger = None
    if enable_trace:
        trace_logger = TraceLogger(
            enabled=True,
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
        if trace_logger and trace_logger.enabled and trace_logger.traces:
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
        print(f"Error processing completion request: {e}")
        await ws_manager.send_message(connection_id, {
            "type": "error",
            "message": f"Processing error: {str(e)}"
        })


async def process_main_with_websocket(
    prompt: str,
    n_runs: int,
    progress_tracker: WebSocketProgressTracker,
    trace_logger: Optional[TraceLogger] = None
):
    """Process completion with WebSocket progress updates."""
    import anyio
    from ..core.llm_client import call_llm
    from ..core.synthesizer import synthesize_result

    # Create memory stream for results
    (tx, rx) = anyio.create_memory_object_stream(n_runs)

    try:
        # Start individual tasks
        async with anyio.create_task_group() as tg:
            for i in range(n_runs):
                task_id = f"run_{i + 1}"
                await progress_tracker.start_task(task_id, f"Run {i + 1}")

                # Generate unique trace_id for each run
                trace_id = (
                    f"run_{i + 1}_{uuid.uuid4().hex[:8]}"
                    if trace_logger and trace_logger.enabled
                    else None
                )

                tg.start_soon(
                    call_llm_with_websocket,
                    prompt,
                    tx.clone(),
                    0.9,
                    None,
                    progress_tracker,
                    task_id,
                    trace_logger,
                    trace_id,
                )

        if hasattr(tx, "aclose"):
            with suppress(Exception):
                await tx.aclose()
        else:  # pragma: no cover - fallback for older anyio versions
            with suppress(Exception):
                tx.close()

        # Collect results
        candidates = []
        async with rx:
            async for result in rx:
                candidates.append(result)

        # Start synthesis
        await progress_tracker.start_synthesis()

        # Synthesize results
        synth_trace_id = (
            f"synthesis_{uuid.uuid4().hex[:8]}"
            if trace_logger and trace_logger.enabled
            else None
        )

        print(f"[DEBUG] Starting synthesis with {len(candidates)} candidates")
        result = await synthesize_result_websocket(
            candidates, progress_tracker, trace_logger, synth_trace_id
        )
        print(f"[DEBUG] Synthesis completed")

        return result

    except Exception as e:
        await progress_tracker.send_error(f"Processing error: {str(e)}")
        raise
    finally:
        if hasattr(tx, "aclose"):
            with suppress(Exception):
                await tx.aclose()
        else:
            with suppress(Exception):
                tx.close()


async def call_llm_with_websocket(
    prompt: str,
    tx,
    temperature: float,
    max_tokens: Optional[int],
    progress_tracker: WebSocketProgressTracker,
    task_id: str,
    trace_logger: Optional[TraceLogger],
    trace_id: Optional[str],
):
    """Call LLM with WebSocket progress updates."""
    from ..core.llm_client import call_llm_streaming

    task_trace = None
    response_content = ""

    async with tx:
        try:
            # Start task trace
            if trace_logger:
                task_trace = trace_logger.start_task(
                    trace_id or task_id,
                    config.model_name,
                    prompt,
                    {"temperature": temperature, "max_tokens": max_tokens}
                )

            # Update progress to show started
            await progress_tracker.update_task_progress(task_id, 10)

            # Make streaming call
            thinking_content = ""
            progress = 10

            print(f"[DEBUG] Starting streaming call for task {task_id}")

            async for chunk_type, content in call_llm_streaming(
                prompt, temperature, max_tokens, trace_logger, trace_id
            ):
                normalized_content = _normalize_stream_content(content)
                preview = normalized_content[:50]
                print(f"[DEBUG] Task {task_id} received {chunk_type}: {preview}...")

                if chunk_type == "thinking":
                    thinking_content += normalized_content
                    if trace_logger and task_trace and normalized_content:
                        trace_logger.log_thinking(task_trace, normalized_content)

                    # Update progress for thinking (10-60%)
                    progress = min(60, progress + 2)
                    await progress_tracker.update_task_progress(
                        task_id, progress, thinking=normalized_content
                    )

                elif chunk_type == "content":
                    response_content += normalized_content
                    if trace_logger and task_trace and normalized_content:
                        trace_logger.log_content(task_trace, normalized_content)

                    # Update progress for content (60-95%)
                    progress = min(95, progress + 1)
                    await progress_tracker.update_task_progress(
                        task_id, progress, content=normalized_content
                    )

                elif chunk_type == "error":
                    print(f"[DEBUG] Error in streaming for task {task_id}: {normalized_content}")
                    # Don't re-raise, just break out of loop
                    break

            print(f"[DEBUG] Task {task_id} completed successfully")

            # Complete task
            if trace_logger and task_trace:
                trace_logger.finish_task(task_trace, success=True)

            await progress_tracker.complete_task(task_id, success=True)

            # Send result to stream
            try:
                await tx.send(response_content)
            except Exception as tx_error:
                print(f"[DEBUG] Error sending to tx for task {task_id}: {tx_error}")

        except CancelledError:
            print(f"[DEBUG] Task {task_id} cancelled")

            if trace_logger and task_trace:
                trace_logger.finish_task(task_trace, success=False, error_msg="Cancelled")

            await progress_tracker.complete_task(
                task_id,
                success=False,
                error="Cancelled by user",
                status="cancelled",
            )
            raise

        except Exception as e:
            print(f"[DEBUG] Exception in task {task_id}: {e}")

            # Handle error
            if trace_logger and task_trace:
                trace_logger.finish_task(task_trace, success=False, error_msg=str(e))

            await progress_tracker.complete_task(task_id, success=False, error=str(e))

            # Send empty result to avoid blocking
            try:
                await tx.send("")
            except Exception as tx_error:
                print(f"[DEBUG] Error sending empty result for task {task_id}: {tx_error}")


async def synthesize_result_websocket(
    candidates: list,
    progress_tracker: WebSocketProgressTracker,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Synthesize multiple candidate results using WebSocket streaming."""
    from ..core.llm_client import call_llm_streaming

    try:
        print(f"[DEBUG] Synthesis: Processing {len(candidates)} candidates")

        # Create synthesis prompt
        numbered = "\n\n".join(
            [
                f"<cand{i}>\n{candidate}\n</cand{i}>"
                for i, candidate in enumerate(candidates)
            ]
        )

        system_prompt = (
            "You are an expert editor. Synthesize ONE best answer from the candidate "
            "answers provided, merging strengths, correcting errors, and removing repetition. "
            "Do not mention the candidates or the synthesis process. Be decisive and clear."
        )

        user_prompt = f"""
        You are given {len(candidates)} candidate answers delimited by tags.

        {numbered}

        Return the single best final answer.
        """

        # Start task trace
        task_trace = None
        if trace_logger and trace_id:
            task_trace = trace_logger.start_task(
                trace_id,
                config.model_name,
                user_prompt,
                {"system": system_prompt, "temperature": 0.2}
            )

        print(f"[DEBUG] Synthesis: Starting streaming call")

        # Make streaming call for synthesis
        thinking_content = ""
        response_content = ""

        # Create complete prompt with system message
        complete_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        async for chunk_type, content in call_llm_streaming(
            complete_prompt, 0.2, None, trace_logger, trace_id
        ):
            normalized_content = _normalize_stream_content(content)
            preview = normalized_content[:50]
            print(f"[DEBUG] Synthesis received {chunk_type}: {preview}...")

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
                print(f"[DEBUG] Synthesis error: {normalized_content}")
                # Don't re-raise, just handle gracefully
                # The error content will be empty, which is fine
                break

        print(f"[DEBUG] Synthesis: Completed with {len(response_content)} chars")

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
        print(f"[DEBUG] Synthesis cancelled")
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
        print(f"[DEBUG] Synthesis exception: {e}")
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
