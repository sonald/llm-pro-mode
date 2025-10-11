
"""LLM client functionality for API calls and streaming."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, Literal, Optional, Tuple

from litellm import acompletion, token_counter

from ..config import Config
from ..logger import error as log_error
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

    def __init__(self, request: LLMRequest, *, model_name: Optional[str]):
        self._logger = request.trace_logger
        self._trace_id = request.trace_id
        self._request = request
        self._task_trace: Optional[dict[str, Any]] = None
        self._model_name = model_name or "unknown"

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
                model_name=self._model_name,
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

    def __init__(
        self,
        *,
        model_name: Optional[str],
        api_base: Optional[str],
        api_key: Optional[str],
        default_temperature: float,
        max_tokens: Optional[int],
        completion_fn=None,
    ) -> None:
        self.model_name = model_name or "unknown"
        self.api_base = api_base
        self.api_key = api_key
        self.default_temperature = default_temperature
        self.max_tokens = max_tokens
        self._completion_fn = completion_fn or acompletion

    async def run(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
        trace_logger: Optional[TraceLogger] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        on_chunk: Optional[Callable[[LLMChunk], None]] = None,
    ) -> LLMResult:
        request = LLMRequest(
            prompt=prompt,
            system=system,
            temperature=self._resolve_temperature(temperature),
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            trace_logger=trace_logger,
            trace_id=trace_id,
            metadata=metadata or {},
        )

        return await self.gather_result(request, on_chunk=on_chunk)

    async def gather_result(
        self,
        request: LLMRequest,
        *,
        on_chunk: Optional[Callable[[LLMChunk], None]] = None,
    ) -> LLMResult:
        """Gather streamed chunks into a final result."""
        parts: list[str] = []
        finish_reason: Optional[str] = None
        token_count = 0
        thinking_count = 0

        async for chunk in self.stream_chunks(request):
            finish_reason = chunk.finish_reason or finish_reason
            if on_chunk:
                on_chunk(chunk)
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

    async def stream_chunks(self, request: LLMRequest) -> AsyncGenerator[LLMChunk, None]:
        """Stream normalized chunks from the configured LLM call."""
        trace = TraceSession(request, model_name=self.model_name).start()
        token_count = 0
        thinking_count = 0
        finish_reason: Optional[str] = None
        error: Optional[Exception] = None

        payload: Dict[str, Any] = {
            "messages": request.build_messages(),
            "model": self.model_name,
            "stream": True,
            "temperature": request.temperature,
        }

        if self.api_base:
            payload["base_url"] = self.api_base

        if self.api_key:
            payload["api_key"] = self.api_key

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
                        thinking_count += _count_tokens(normalized_reasoning, self.model_name)
                        trace.log_thinking(normalized_reasoning)
                        yield LLMChunk(
                            kind="thinking",
                            text=normalized_reasoning,
                            token_count=token_count,
                            thinking_count=thinking_count,
                            finish_reason=finish_reason,
                        )

                if hasattr(delta, "content") and delta.content:
                    token_count += _count_tokens(delta.content, self.model_name)
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

    async def stream_text(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
        trace_logger: Optional[TraceLogger] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """Yield text chunks with retry support for streaming interfaces."""

        request = LLMRequest(
            prompt=prompt,
            system=system,
            temperature=self._resolve_temperature(temperature),
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            trace_logger=trace_logger,
            trace_id=trace_id,
            metadata=metadata or {},
        )

        max_attempts = 3
        attempt = 0
        last_error: Optional[BaseException] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                async for chunk in self.stream_chunks(request):
                    yield (chunk.kind, chunk.text)
                return
            except TRANSIENT_STREAM_ERRORS as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(0.2 * attempt)
                continue
            except Exception as exc:  # pragma: no cover
                log_error("Error calling LLM: %s", exc)
                yield ("error", f"Error calling LLM: {exc}")
                return

        if last_error is not None:
            log_error("Error calling LLM: %s", last_error)
            yield ("error", f"Error calling LLM: {last_error}")

    def _resolve_temperature(self, value: Optional[float]) -> float:
        if value is not None:
            return value
        return self.default_temperature


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


def _count_tokens(text: str, model_name: str) -> int:
    """Count tokens for the provided text with graceful fallback."""
    if not text:
        return 0

    try:
        return int(token_counter(model=model_name, text=text))
    except Exception:
        return max(1, len(text) // 4)


TRANSIENT_STREAM_ERRORS: Tuple[type[BaseException], ...] = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


async def call_llm_streaming(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system: Optional[str] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    config: Optional[Config] = None,
) -> AsyncGenerator[Tuple[str, str], None]:
    """Compatibility wrapper that streams text using a temporary LLM client."""

    cfg = config or Config()
    client = LLMClient(
        model_name=cfg.model_name,
        api_base=cfg.api_base,
        api_key=cfg.api_key,
        default_temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )

    async for chunk_type, content in client.stream_text(
        prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        system=system,
        trace_logger=trace_logger,
        trace_id=trace_id,
        metadata=metadata,
    ):
        yield (chunk_type, content)
