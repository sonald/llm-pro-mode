"""Result synthesis functionality."""

from typing import Optional, List
import anyio
from rich.progress import Progress, TaskID

from .llm_client import call_llm, call_llm_tui
from ..config import config
from ..tracing.logger import TraceLogger


async def synthesize_result(
    candidates: List[str],
    progress: Optional[Progress] = None,
    task_id: Optional[TaskID] = None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Synthesize multiple candidate results into one best answer."""
    numbered = "\n\n".join(
        [
            f"<cand{i}>\n{candidate}\n</cand{i}>"
            for i, candidate in enumerate(candidates)
        ]
    )
    system = (
        "You are an expert editor. Synthesize ONE best answer from the candidate "
        "answers provided, merging strengths, correcting errors, and removing repetition. "
        "Do not mention the candidates or the synthesis process. Be decisive and clear."
    )

    user = f"""
    You are given {len(candidates)} candidate answers delimited by tags.

    {numbered}

    Return the single best final answer.
    """

    (tx, rx) = anyio.create_memory_object_stream(1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            call_llm,
            user,
            tx,
            config.synthesis_temperature,
            system,
            progress,
            task_id,
            trace_logger,
            trace_id,
        )
        async with rx:
            async for result in rx:
                return result


async def synthesize_result_tui(
    candidates: List[str],
    tui_app=None,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
):
    """Synthesize multiple candidate results into one best answer with TUI support."""
    numbered = "\n\n".join(
        [
            f"<cand{i}>\n{candidate}\n</cand{i}>"
            for i, candidate in enumerate(candidates)
        ]
    )
    system = (
        "You are an expert editor. Synthesize ONE best answer from the candidate "
        "answers provided, merging strengths, correcting errors, and removing repetition. "
        "Do not mention the candidates or the synthesis process. Be decisive and clear."
    )

    user = f"""
    You are given {len(candidates)} candidate answers delimited by tags.

    {numbered}

    Return the single best final answer.
    """

    (tx, rx) = anyio.create_memory_object_stream(1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            call_llm_tui,
            user,
            tx,
            config.synthesis_temperature,
            system,
            tui_app,
            "Synthesis",
            trace_logger,
            trace_id,
        )
        async with rx:
            async for result in rx:
                return result
