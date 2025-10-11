"""Result synthesis functionality."""

from __future__ import annotations

from typing import Callable, List, Optional

from .llm_client import LLMChunk, LLMClient, LLMResult
from ..tracing.logger import TraceLogger


def _build_synthesis_prompt(candidates: List[str]) -> tuple[str, str]:
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

    return system, user


async def synthesize_result(
    client: LLMClient,
    candidates: list[str],
    *,
    temperature: float,
    trace_logger: Optional[TraceLogger] = None,
    trace_id: Optional[str] = None,
    on_chunk: Optional[Callable[[LLMChunk], None]] = None,
) -> LLMResult:
    """Run a synthesis pass over candidate responses."""

    system, user = _build_synthesis_prompt(candidates)
    return await client.run(
        user,
        temperature=temperature,
        system=system,
        trace_logger=trace_logger,
        trace_id=trace_id,
        on_chunk=on_chunk,
    )
