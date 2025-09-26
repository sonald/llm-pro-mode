"""Main processing logic for parallel LLM calls and synthesis."""

import uuid
from typing import Optional
import anyio
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TaskID

from .llm_client import call_llm, call_llm_tui
from .synthesizer import synthesize_result, synthesize_result_tui
from ..config import console
from ..tracing.logger import TraceLogger


async def main(
    prompt: str,
    n_runs: int = 3,
    show_progress: bool = False,
    tui_app=None,
    trace_logger: Optional[TraceLogger] = None,
):
    """Main processing function for parallel LLM calls and synthesis."""
    (tx, rx) = anyio.create_memory_object_stream(n_runs)
    progress: Optional[Progress] = None

    try:
        if show_progress:
            progress = Progress(
                SpinnerColumn(spinner_name="dots"),
                TextColumn("{task.description}"),
                TextColumn("[dim]{task.fields[thinking_count]} thinking"),
                TextColumn("[dim]{task.fields[token_count]} tokens"),
                TimeElapsedColumn(),
                expand=True,
                console=console,
            )
            progress.start()

        # Create task group to spawn n_runs tasks
        async with anyio.create_task_group() as tg:
            for i in range(n_runs):
                # Generate unique trace_id for each run
                trace_id = (
                    f"run_{i + 1}_{uuid.uuid4().hex[:8]}"
                    if trace_logger and trace_logger.enabled
                    else None
                )

                if progress is not None:
                    task_id = progress.add_task(
                        description=f"Run {i + 1}",
                        start=True,
                        token_count=0,
                        thinking_count=0,
                    )
                    tg.start_soon(
                        call_llm,
                        prompt,
                        tx.clone(),
                        0.9,
                        None,
                        progress,
                        task_id,
                        trace_logger,
                        trace_id,
                    )
                elif tui_app:
                    tg.start_soon(
                        call_llm_tui,
                        prompt,
                        tx.clone(),
                        0.9,
                        None,
                        tui_app,
                        f"Run {i + 1}",
                        trace_logger,
                        trace_id,
                    )
                else:
                    tg.start_soon(
                        call_llm,
                        prompt,
                        tx.clone(),
                        0.9,
                        None,
                        None,
                        None,
                        trace_logger,
                        trace_id,
                    )
        tx.close()

        candidates = []
        async with rx:
            async for result in rx:
                candidates.append(result)

        synth_task: Optional[TaskID] = None
        synth_trace_id = (
            f"synthesis_{uuid.uuid4().hex[:8]}"
            if trace_logger and trace_logger.enabled
            else None
        )

        if progress is not None:
            synth_task = progress.add_task(
                description="Synthesizing",
                start=True,
                token_count=0,
                thinking_count=0,
            )
            result = await synthesize_result(
                candidates, progress, synth_task, trace_logger, synth_trace_id
            )
            progress.update(synth_task, description="Synthesizing done")
            progress.stop_task(synth_task)
        elif tui_app:
            if tui_app:
                tui_app.update_progress("Synthesis", "Combining results")
            result = await synthesize_result_tui(
                candidates, tui_app, trace_logger, synth_trace_id
            )
            if tui_app:
                tui_app.update_progress("Synthesis", "Completed")
        else:
            result = await synthesize_result(
                candidates, None, None, trace_logger, synth_trace_id
            )

        # Save traces and show statistics
        if trace_logger and trace_logger.enabled and trace_logger.traces:
            trace_file = trace_logger.save_traces()
            stats = trace_logger.get_stats()
            console.print(f"\n[bold green]轨迹已保存到: {trace_file}[/bold green]")
            console.print(
                f"[dim]统计信息: {stats['total_tasks']} 个任务, "
                f"成功率: {stats['success_rate']:.2%}, "
                f"总token: {stats['total_tokens']}, "
                f"平均耗时: {stats['avg_duration_ms']:.0f}ms[/dim]"
            )

        return result
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if progress is not None:
            progress.stop()