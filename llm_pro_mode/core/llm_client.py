"""LLM client functionality for API calls and streaming."""

from typing import Optional, AsyncGenerator, Tuple, Any
import json
from litellm import acompletion
from anyio.streams.memory import MemoryObjectSendStream
from rich.progress import Progress, TaskID

from ..config import config, console
from ..tracing.logger import TraceLogger


def _normalize_reasoning_payload(value: Any) -> str:
    """Normalize reasoning/content payloads to plain text."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_normalize_reasoning_payload(item) for item in value if item is not None)
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                candidate = _normalize_reasoning_payload(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def call_llm_tui(
    prompt: str,
    tx: MemoryObjectSendStream,
    temperature: float = 0.7,
    system: Optional[str] = None,
    tui_app=None,
    task_name: str = "Task",
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Call LLM with TUI integration for progress updates."""
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    # Start trace logging
    task_trace = None
    if trace_logger and trace_id:
        full_prompt = f"System: {system}\n\nUser: {prompt}" if system else prompt
        task_trace = trace_logger.start_task(
            task_id=trace_id,
            model_name=config.model_name or "unknown",
            input_prompt=full_prompt,
            metadata={"temperature": temperature},
        )

    # Update TUI progress
    if tui_app:
        tui_app.update_progress(task_name, "Starting")

    try:
        response = await acompletion(
            messages=messages,
            model=config.model_name,
            base_url=config.api_base,
            api_key=config.api_key,
            stream=True,
            temperature=temperature,
        )

        if tui_app:
            tui_app.update_progress(task_name, "Receiving response")

        result = ""
        token_count = 0
        thinking_count = 0
        finish_reason = None
        async for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                finish_reason = getattr(chunk.choices[0], "finish_reason", "Done")

                # Handle models which emit reasoning/thinking tokens
                reasoning_text = None
                if hasattr(delta, "reasoning_content") and getattr(
                    delta, "reasoning_content"
                ):
                    reasoning_text = getattr(delta, "reasoning_content")
                elif hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_text = getattr(delta, "reasoning")

                if reasoning_text:
                    normalized_reasoning = _normalize_reasoning_payload(reasoning_text)
                    thinking_count += len(normalized_reasoning)
                    # Log thinking content to trace
                    if trace_logger and normalized_reasoning:
                        trace_logger.log_thinking(task_trace, normalized_reasoning)
                    if tui_app:
                        tui_app.update_progress(task_name, "Thinking", f"{thinking_count} thinking tokens")

                if hasattr(delta, "content") and delta.content:
                    result += delta.content
                    token_count += len(delta.content)
                    # Log content to trace
                    if trace_logger:
                        trace_logger.log_content(task_trace, delta.content)
                    if tui_app:
                        tui_app.update_progress(task_name, "Generating", f"{token_count} tokens")

        async with tx:
            await tx.send(result)

        if tui_app:
            tui_app.update_progress(task_name, f"Completed - {finish_reason}", f"{token_count} tokens, {thinking_count} thinking")

        # Complete trace logging
        if trace_logger:
            trace_logger.finish_task(task_trace, success=True)
        return result
    except Exception as e:
        if tui_app:
            tui_app.update_progress(task_name, "Error", str(e))

        # Log error to trace
        if trace_logger:
            trace_logger.finish_task(task_trace, success=False, error_msg=str(e))
        console.print(f"[bold red]Error calling LLM: {e}[/]")


async def call_llm(
    prompt: str,
    tx: MemoryObjectSendStream,
    temperature: float = 0.7,
    system: Optional[str] = None,
    progress: Optional[Progress] = None,
    task_id: Optional[TaskID] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Call LLM with progress bar integration."""
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    # Start trace logging
    task_trace = None
    if trace_logger and trace_id:
        full_prompt = f"System: {system}\n\nUser: {prompt}" if system else prompt
        task_trace = trace_logger.start_task(
            task_id=trace_id,
            model_name=config.model_name or "unknown",
            input_prompt=full_prompt,
            metadata={"temperature": temperature},
        )

    try:
        response = await acompletion(
            messages=messages,
            model=config.model_name,
            base_url=config.api_base,
            api_key=config.api_key,
            stream=True,
            temperature=temperature,
        )

        result = ""
        token_count = 0
        thinking_count = 0
        finish_reason = None
        async for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                finish_reason = getattr(chunk.choices[0], "finish_reason", "Done")

                # Handle models which emit reasoning/thinking tokens
                reasoning_text = None
                if hasattr(delta, "reasoning_content") and getattr(
                    delta, "reasoning_content"
                ):
                    reasoning_text = getattr(delta, "reasoning_content")
                elif hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_text = getattr(delta, "reasoning")

                if reasoning_text:
                    normalized_reasoning = _normalize_reasoning_payload(reasoning_text)
                    thinking_count += len(normalized_reasoning)
                    # Log thinking content to trace
                    if trace_logger and normalized_reasoning:
                        trace_logger.log_thinking(task_trace, normalized_reasoning)
                    if progress is not None and task_id is not None:
                        progress.update(
                            task_id,
                            token_count=token_count,
                            thinking_count=thinking_count,
                        )

                if hasattr(delta, "content") and delta.content:
                    result += delta.content
                    token_count += len(delta.content)
                    # Log content to trace
                    if trace_logger:
                        trace_logger.log_content(task_trace, delta.content)
                    if progress is not None and task_id is not None:
                        progress.update(
                            task_id,
                            token_count=token_count,
                            thinking_count=thinking_count,
                        )

        async with tx:
            await tx.send(result)

        if progress is not None and task_id is not None:
            progress.update(
                task_id,
                description=f"{task_id} {finish_reason}",
                token_count=token_count,
                thinking_count=thinking_count,
            )
            progress.stop_task(task_id)

        # Complete trace logging
        if trace_logger:
            trace_logger.finish_task(task_trace, success=True)
        return result
    except Exception as e:
        if progress is not None and task_id is not None:
            progress.update(
                task_id,
                description=f"{task_id} Error",
                token_count=token_count,
                thinking_count=thinking_count,
            )
            progress.stop_task(task_id)

        # Log error to trace
        if trace_logger:
            trace_logger.finish_task(task_trace, success=False, error_msg=str(e))
        console.print(f"[bold red]Error calling LLM: {e}[/]")


async def call_llm_streaming(
    prompt: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
) -> AsyncGenerator[Tuple[str, str], None]:
    """
    Call LLM with streaming support for WebSocket integration.

    Yields:
        Tuple[str, str]: (chunk_type, content) where chunk_type is 'thinking' or 'content'
    """
    messages = [{"role": "user", "content": prompt}]

    # Start trace logging
    task_trace = None
    if trace_logger and trace_id:
        task_trace = trace_logger.start_task(
            task_id=trace_id,
            model_name=config.model_name or "unknown",
            input_prompt=prompt,
            metadata={"temperature": temperature, "max_tokens": max_tokens},
        )

    try:
        response = await acompletion(
            messages=messages,
            model=config.model_name,
            base_url=config.api_base,
            api_key=config.api_key,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        async for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                # Handle thinking/reasoning content
                reasoning_text = None
                if hasattr(delta, "reasoning_content") and getattr(delta, "reasoning_content"):
                    reasoning_text = getattr(delta, "reasoning_content")
                elif hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_text = getattr(delta, "reasoning")

                if reasoning_text:
                    normalized_reasoning = _normalize_reasoning_payload(reasoning_text)
                    if trace_logger and task_trace and normalized_reasoning:
                        trace_logger.log_thinking(task_trace, normalized_reasoning)
                    if normalized_reasoning:
                        yield ("thinking", normalized_reasoning)

                # Handle regular content
                if hasattr(delta, "content") and delta.content:
                    if trace_logger and task_trace:
                        trace_logger.log_content(task_trace, delta.content)
                    yield ("content", delta.content)

        # Complete trace logging
        if trace_logger and task_trace:
            trace_logger.finish_task(task_trace, success=True)

    except Exception as e:
        # Log error to trace
        if trace_logger and task_trace:
            trace_logger.finish_task(task_trace, success=False, error_msg=str(e))

        # Yield error as content
        yield ("error", f"Error calling LLM: {str(e)}")
        # Don't re-raise - let the caller handle the error message
