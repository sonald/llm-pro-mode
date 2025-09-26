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

        try:
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

        except (KeyboardInterrupt, anyio.get_cancelled_exc_class()):
            # 清理进度条
            if progress:
                progress.stop()
            if tui_app:
                # 更新所有运行中的任务状态为中断
                for i in range(n_runs):
                    tui_app.update_progress(f"Run {i + 1}", "Interrupted")
                tui_app.update_progress("Synthesis", "Interrupted")

            # 关闭发送端确保接收端能正常结束
            try:
                tx.close()
            except anyio.ClosedResourceError:
                pass  # 已经关闭

            # 收集已完成的部分结果
            candidates = []
            try:
                async with rx:
                    async for result in rx:
                        candidates.append(result)
            except (anyio.ClosedResourceError, anyio.get_cancelled_exc_class()):
                pass  # 正常的资源关闭

            # 如果有部分结果，尝试快速合成
            if candidates:
                console.print(f"\n[yellow]⚠️  任务被中断，正在处理已完成的 {len(candidates)} 个结果...[/yellow]")

                # 对已有结果进行简化合成
                if len(candidates) == 1:
                    return candidates[0]
                else:
                    # 简单拼接多个结果而不是复杂合成
                    combined = "\n\n".join(f"结果 {i+1}:\n{result}" for i, result in enumerate(candidates))
                    return f"[注意：任务被中断，以下是已完成的部分结果]\n\n{combined}"
            else:
                console.print("\n[yellow]⚠️  没有完成的结果可以返回[/yellow]")
                return None

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

    except (KeyboardInterrupt, anyio.get_cancelled_exc_class()):
        # 这个中断来自合成阶段
        console.print("\n[yellow]⚠️  合成阶段被中断[/yellow]")
        # 传播中断信号到上层
        raise KeyboardInterrupt("任务被用户中断")
    except Exception as e:
        console.print(f"[bold red]❌ 处理错误: {e}[/bold red]")
        return None
    finally:
        if progress is not None:
            progress.stop()