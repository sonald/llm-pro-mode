
"""LLM client functionality for API calls and streaming."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Literal, Optional, Tuple

from anyio.streams.memory import MemoryObjectSendStream
from litellm import acompletion, token_counter
from rich.progress import Progress, TaskID

from ..config import config, console
from ..tracing.logger import TraceLogger


@dataclass(slots=True)
class LLMRequest:
    """Container for an LLM request configuration."""

    prompt: str
    system: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    trace_logger: Optional[TraceLogger] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def build_messages(self) -> list[dict[str, str]]:
        """Build litellm-compatible messages sequence."""
        messages = [{"role": "user", "content": self.prompt}]
        if self.system:
            messages.insert(0, {"role": "system", "content": self.system})
        return messages

    def prompt_for_trace(self) -> str:
        """Return combined prompt string for trace logging."""
        if self.system:
            return f"System: {self.system}\n\nUser: {self.prompt}"
        return self.prompt


@dataclass(slots=True)
class LLMChunk:
    """Represents a normalized piece of streaming output."""

    kind: Literal["thinking", "content"]
    text: str
    token_count: int
    thinking_count: int
    finish_reason: Optional[str] = None


@dataclass(slots=True)
class LLMResult:
    """Aggregated result returned by LLM streaming."""

    content: str
    finish_reason: Optional[str]
    token_count: int
    thinking_count: int


class TraceSession:
    """Utility class that manages trace lifecycle for an LLM request."""

    def __init__(self, request: LLMRequest):
        self._logger = request.trace_logger
        self._trace_id = request.trace_id
        self._request = request
        self._task_trace: Optional[dict[str, Any]] = None

    def start(self) -> "TraceSession":
        """Start trace logging if available."""
        if self._logger and self._trace_id:
            metadata: Dict[str, Any] = {"temperature": self._request.temperature}
            if self._request.max_tokens is not None:
                metadata["max_tokens"] = self._request.max_tokens
            if self._request.metadata:
                metadata.update(self._request.metadata)

            self._task_trace = self._logger.start_task(
                task_id=self._trace_id,
                model_name=config.model_name or "unknown",
                input_prompt=self._request.prompt_for_trace(),
                metadata=metadata,
            )
        return self

    def log_thinking(self, text: str) -> None:
        if self._logger and self._task_trace and text:
            self._logger.log_thinking(self._task_trace, text)

    def log_content(self, text: str) -> None:
        if self._logger and self._task_trace and text:
            self._logger.log_content(self._task_trace, text)

    def finish(self, success: bool, error_msg: Optional[str] = None) -> None:
        if self._logger and self._task_trace is not None:
            self._logger.finish_task(self._task_trace, success=success, error_msg=error_msg)


class LLMClient:
    """High-level helper that coordinates streaming LLM calls."""

    def __init__(self):
        self._completion_fn = acompletion

    async def stream_chunks(self, request: LLMRequest) -> AsyncGenerator[LLMChunk, None]:
        """Stream normalized chunks from the configured LLM call."""
        trace = TraceSession(request).start()
        token_count = 0
        thinking_count = 0
        finish_reason: Optional[str] = None
        error: Optional[Exception] = None

        payload: Dict[str, Any] = {
            "messages": request.build_messages(),
            "model": config.model_name,
            "base_url": config.api_base,
            "api_key": config.api_key,
            "stream": True,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        try:
            response = await self._completion_fn(**payload)

            async for chunk in response:
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue

                choice = chunk.choices[0]
                finish_reason = getattr(choice, "finish_reason", finish_reason)
                delta = choice.delta

                reasoning_payload = None
                if hasattr(delta, "reasoning_content") and getattr(delta, "reasoning_content"):
                    reasoning_payload = getattr(delta, "reasoning_content")
                elif hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_payload = getattr(delta, "reasoning")

                if reasoning_payload is not None:
                    normalized_reasoning = _normalize_reasoning_payload(reasoning_payload)
                    if normalized_reasoning:
                        thinking_count += _count_tokens(normalized_reasoning)
                        trace.log_thinking(normalized_reasoning)
                        yield LLMChunk(
                            kind="thinking",
                            text=normalized_reasoning,
                            token_count=token_count,
                            thinking_count=thinking_count,
                            finish_reason=finish_reason,
                        )

                if hasattr(delta, "content") and delta.content:
                    token_count += _count_tokens(delta.content)
                    trace.log_content(delta.content)
                    yield LLMChunk(
                        kind="content",
                        text=delta.content,
                        token_count=token_count,
                        thinking_count=thinking_count,
                        finish_reason=finish_reason,
                    )

        except Exception as exc:  # pragma: no cover - exercised via higher-level wrappers
            error = exc
            raise
        finally:
            trace.finish(success=error is None, error_msg=str(error) if error else None)

    async def gather_result(self, request: LLMRequest) -> LLMResult:
        """Collect the full response content while streaming.

        Consumers who do not need per-chunk access can use this helper to
        retrieve the aggregated content alongside counters.
        """
        parts: list[str] = []
        finish_reason: Optional[str] = None
        token_count = 0
        thinking_count = 0

        async for chunk in self.stream_chunks(request):
            finish_reason = chunk.finish_reason or finish_reason
            if chunk.kind == "thinking":
                thinking_count = chunk.thinking_count
            elif chunk.kind == "content":
                parts.append(chunk.text)
                token_count = chunk.token_count

        return LLMResult(
            content="".join(parts),
            finish_reason=finish_reason,
            token_count=token_count,
            thinking_count=thinking_count,
        )


def _normalize_reasoning_payload(value: Any) -> str:
    """Normalize reasoning/content payloads to plain text."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            _normalize_reasoning_payload(item) for item in value if item is not None
        )
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                candidate = _normalize_reasoning_payload(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _resolve_temperature(value: Optional[float]) -> float:
    """Return effective sampling temperature with global fallback."""
    if value is not None:
        return value
    return config.temperature


def _count_tokens(text: str) -> int:
    """Count tokens for the provided text with graceful fallback."""
    if not text:
        return 0

    model_name = config.model_name or "gpt-3.5-turbo"
    try:
        return int(token_counter(model=model_name, text=text))
    except Exception:
        # Fall back to an approximate character-based heuristic when token counting fails.
        return max(1, len(text) // 4)


async def call_llm_tui(
    prompt: str,
    tx: MemoryObjectSendStream,
    temperature: Optional[float] = None,
    system: Optional[str] = None,
    tui_app=None,
    task_name: str = "Task",
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Call LLM with TUI integration for progress updates."""
    max_token_limit = config.max_tokens if config.max_tokens is not None else None

    request = LLMRequest(
        prompt=prompt,
        system=system,
        temperature=_resolve_temperature(temperature),
        max_tokens=max_token_limit,
        trace_logger=trace_logger,
        trace_id=trace_id,
    )
    client = LLMClient()

    if tui_app:
        tui_app.update_progress(task_name, "Starting")

    parts: list[str] = []
    token_count = 0
    thinking_count = 0
    finish_reason: Optional[str] = None

    try:
        async for chunk in client.stream_chunks(request):
            finish_reason = chunk.finish_reason or finish_reason
            if chunk.kind == "thinking":
                thinking_count = chunk.thinking_count
                if tui_app:
                    tui_app.update_progress(
                        task_name,
                        "Thinking",
                        f"{thinking_count} thinking tokens",
                    )
            elif chunk.kind == "content":
                parts.append(chunk.text)
                token_count = chunk.token_count
                if tui_app:
                    tui_app.update_progress(
                        task_name,
                        "Generating",
                        f"{token_count} tokens",
                    )

        result_text = "".join(parts)
        async with tx:
            await tx.send(result_text)

        if tui_app:
            tui_app.update_progress(
                task_name,
                f"Completed - {finish_reason or 'Done'}",
                f"{token_count} tokens, {thinking_count} thinking",
            )
        return result_text
    except Exception as exc:  # pragma: no cover - integration behaviour validated elsewhere
        if tui_app:
            tui_app.update_progress(task_name, "Error", str(exc))
        console.print(f"[bold red]Error calling LLM: {exc}[/]")


async def call_llm(
    prompt: str,
    tx: MemoryObjectSendStream,
    temperature: Optional[float] = None,
    system: Optional[str] = None,
    progress: Optional[Progress] = None,
    task_id: Optional[TaskID] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Call LLM with progress bar integration."""
    max_token_limit = config.max_tokens if config.max_tokens is not None else None

    request = LLMRequest(
        prompt=prompt,
        system=system,
        temperature=_resolve_temperature(temperature),
        max_tokens=max_token_limit,
        trace_logger=trace_logger,
        trace_id=trace_id,
    )
    client = LLMClient()

    parts: list[str] = []
    token_count = 0
    thinking_count = 0
    finish_reason: Optional[str] = None

    try:
        async for chunk in client.stream_chunks(request):
            finish_reason = chunk.finish_reason or finish_reason
            if chunk.kind == "thinking":
                thinking_count = chunk.thinking_count
                if progress is not None and task_id is not None:
                    progress.update(
                        task_id,
                        token_count=token_count,
                        thinking_count=thinking_count,
                    )
            elif chunk.kind == "content":
                parts.append(chunk.text)
                token_count = chunk.token_count
                if progress is not None and task_id is not None:
                    progress.update(
                        task_id,
                        token_count=token_count,
                        thinking_count=thinking_count,
                    )

        result_text = "".join(parts)
        async with tx:
            await tx.send(result_text)

        if progress is not None and task_id is not None:
            progress.update(
                task_id,
                description=f"{task_id} {finish_reason or 'Done'}",
                token_count=token_count,
                thinking_count=thinking_count,
            )
            progress.stop_task(task_id)

        return result_text
    except Exception as exc:  # pragma: no cover - integration behaviour validated elsewhere
        if progress is not None and task_id is not None:
            progress.update(
                task_id,
                description=f"{task_id} Error",
                token_count=token_count,
                thinking_count=thinking_count,
            )
            progress.stop_task(task_id)
        console.print(f"[bold red]Error calling LLM: {exc}[/]")


async def call_llm_streaming(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system: Optional[str] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Tuple[str, str], None]:
    """
    Call LLM with streaming support for WebSocket integration.

    Yields:
        Tuple[str, str]: (chunk_type, content) where chunk_type is 'thinking' or 'content'
    """
    effective_max_tokens = max_tokens if max_tokens is not None else config.max_tokens

    request = LLMRequest(
        prompt=prompt,
        system=system,
        temperature=_resolve_temperature(temperature),
        max_tokens=effective_max_tokens,
        trace_logger=trace_logger,
        trace_id=trace_id,
        metadata=metadata or {},
    )
    client = LLMClient()

    try:
        async for chunk in client.stream_chunks(request):
            yield (chunk.kind, chunk.text)
    except Exception as exc:
        yield ("error", f"Error calling LLM: {exc}")
        # Don't re-raise - let the caller handle the error message
