"""Main processing logic for parallel LLM calls and synthesis."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

import anyio

from .llm_client import LLMChunk, LLMClient, LLMResult
from .synthesizer import synthesize_result
from ..config import Config
from ..logger import get_logger
from ..tracing.logger import TraceLogger


_logger = get_logger()


@dataclass(frozen=True)
class RunContext:
    """Metadata describing a single model invocation."""

    run_id: str
    index: int
    trace_id: Optional[str]


@dataclass
class RunOutput:
    """Result of a single candidate generation."""

    context: RunContext
    result: Optional[LLMResult] = None
    error: Optional[BaseException] = None


@dataclass
class ProcessorResult:
    """Aggregated execution outcome."""

    prompt: str
    runs: List[RunOutput]
    final: Optional[LLMResult]
    partial_text: Optional[str] = None
    interrupted: bool = False

    def best_text(self) -> Optional[str]:
        if self.final:
            return self.final.content
        if self.partial_text:
            return self.partial_text
        for run in self.runs:
            if run.result:
                return run.result.content
        return None


@dataclass
class ProcessorHooks:
    """Optional callbacks for progress reporting."""

    run_start: Optional[Callable[[RunContext], None]] = None
    run_chunk: Optional[Callable[[RunContext, LLMChunk], None]] = None
    run_complete: Optional[Callable[[RunContext, LLMResult], None]] = None
    run_error: Optional[Callable[[RunContext, BaseException], None]] = None
    synthesis_start: Optional[Callable[[], None]] = None
    synthesis_chunk: Optional[Callable[[LLMChunk], None]] = None
    synthesis_complete: Optional[Callable[[LLMResult], None]] = None
    synthesis_error: Optional[Callable[[BaseException], None]] = None
    cancelled: Optional[Callable[[], None]] = None


class Processor:
    """Coordinates parallel candidate generation and synthesis."""

    def __init__(self, config: Config, hooks: Optional[ProcessorHooks] = None):
        self._config = config
        self._hooks = hooks or ProcessorHooks()

    def _build_client(self, *, default_temperature: float) -> LLMClient:
        return LLMClient(
            model_name=self._config.model_name,
            api_base=self._config.api_base,
            api_key=self._config.api_key,
            default_temperature=default_temperature,
            max_tokens=self._config.max_tokens,
        )

    async def run(
        self,
        prompt: str,
        *,
        n_runs: Optional[int] = None,
        trace_logger: Optional[TraceLogger] = None,
    ) -> ProcessorResult:
        run_count = n_runs or self._config.n_runs
        run_outputs: List[RunOutput] = []
        interrupted = False

        run_client = self._build_client(default_temperature=self._config.temperature)

        cancel_exc = anyio.get_cancelled_exc_class()

        try:
            async with anyio.create_task_group() as tg:
                for index in range(run_count):
                    trace_id = (
                        f"run_{index + 1}_{uuid.uuid4().hex[:8]}"
                        if trace_logger and getattr(trace_logger, "enabled", False)
                        else None
                    )
                    context = RunContext(
                        run_id=f"run_{index + 1}",
                        index=index,
                        trace_id=trace_id,
                    )
                    tg.start_soon(
                        self._execute_single_run,
                        run_client,
                        prompt,
                        context,
                        trace_logger,
                        run_outputs,
                    )
        except (KeyboardInterrupt, cancel_exc):
            interrupted = True
            if self._hooks.cancelled:
                self._hooks.cancelled()
        except Exception as exc:  # pragma: no cover - defensive
            _logger.error("候选运行过程中出现未处理异常: %s", exc)
            run_outputs.append(
                RunOutput(
                    context=RunContext(run_id="run-error", index=-1, trace_id=None),
                    error=exc,
                )
            )

        run_outputs.sort(key=lambda item: item.context.index)
        successful = [output for output in run_outputs if output.result]

        final_result: Optional[LLMResult] = None
        partial_text: Optional[str] = None

        if interrupted:
            if len(successful) == 1:
                final_result = successful[0].result
            elif len(successful) > 1:
                combined = "\n\n".join(
                    f"结果 {i + 1}:\n{output.result.content}"
                    for i, output in enumerate(successful)
                    if output.result
                )
                partial_text = (
                    "[注意：任务被中断，以下是已完成的部分结果]\n\n" + combined
                )
        elif successful:
            if len(successful) == 1:
                final_result = successful[0].result
            else:
                final_result = await self._run_synthesis(
                    [output.result.content for output in successful if output.result],
                    trace_logger=trace_logger,
                )
                if final_result is None:
                    final_result = successful[0].result

        return ProcessorResult(
            prompt=prompt,
            runs=run_outputs,
            final=final_result,
            partial_text=partial_text,
            interrupted=interrupted,
        )

    async def _execute_single_run(
        self,
        client: LLMClient,
        prompt: str,
        context: RunContext,
        trace_logger: Optional[TraceLogger],
        sink: List[RunOutput],
    ) -> None:
        if self._hooks.run_start:
            self._hooks.run_start(context)

        def _on_chunk(chunk: LLMChunk) -> None:
            if self._hooks.run_chunk:
                self._hooks.run_chunk(context, chunk)

        try:
            result = await client.run(
                prompt,
                trace_logger=trace_logger,
                trace_id=context.trace_id,
                metadata={"run_index": context.index},
                on_chunk=_on_chunk,
            )
            sink.append(RunOutput(context=context, result=result))
            if self._hooks.run_complete:
                self._hooks.run_complete(context, result)
        except Exception as exc:  # pragma: no cover - integration level
            sink.append(RunOutput(context=context, error=exc))
            if self._hooks.run_error:
                self._hooks.run_error(context, exc)
            _logger.warning("候选运行失败 (run=%s): %s", context.run_id, exc)

    async def _run_synthesis(
        self,
        candidates: List[str],
        *,
        trace_logger: Optional[TraceLogger],
    ) -> Optional[LLMResult]:
        if self._hooks.synthesis_start:
            self._hooks.synthesis_start()

        synthesis_client = self._build_client(
            default_temperature=self._config.synthesis_temperature
        )

        trace_id = (
            f"synthesis_{uuid.uuid4().hex[:8]}"
            if trace_logger and getattr(trace_logger, "enabled", False)
            else None
        )

        def _on_chunk(chunk: LLMChunk) -> None:
            if self._hooks.synthesis_chunk:
                self._hooks.synthesis_chunk(chunk)

        try:
            result = await synthesize_result(
                synthesis_client,
                candidates,
                temperature=self._config.synthesis_temperature,
                trace_logger=trace_logger,
                trace_id=trace_id,
                on_chunk=_on_chunk,
            )
            if self._hooks.synthesis_complete:
                self._hooks.synthesis_complete(result)
            return result
        except Exception as exc:  # pragma: no cover - integration level
            if self._hooks.synthesis_error:
                self._hooks.synthesis_error(exc)
            _logger.error("结果合成失败: %s", exc)
            return None
