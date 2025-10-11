"""Command-line interface functionality."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, Optional

import anyio
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from ..config import Config
from ..core.processor import Processor, ProcessorHooks, ProcessorResult, RunContext
from ..logger import console, error as log_error, warning as log_warning
from ..tracing.logger import TraceLogger
from .support import create_trace_logger


@dataclass
class CLIProgress:
    """Adapter that maps processor hooks to Rich progress updates."""

    progress: Progress
    tasks: Dict[str, TaskID]
    synthesis_task: Optional[TaskID] = None

    def __init__(self) -> None:
        self.progress = Progress(
            SpinnerColumn(spinner_name="dots"),
            TextColumn("{task.description}"),
            TextColumn("[dim]{task.fields[thinking_count]} thinking"),
            TextColumn("[dim]{task.fields[token_count]} tokens"),
            TimeElapsedColumn(),
            console=console,
            expand=True,
        )
        self.tasks = {}
        self.synthesis_task = None

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

    def start(self) -> None:
        self.progress.start()

    def stop(self) -> None:
        self.progress.stop()

    def on_run_start(self, context: RunContext) -> None:
        task_id = self.progress.add_task(
            description=f"Run {context.index + 1}",
            start=True,
            token_count=0,
            thinking_count=0,
        )
        self.tasks[context.run_id] = task_id

    def on_run_chunk(self, context: RunContext, chunk) -> None:
        task_id = self.tasks.get(context.run_id)
        if task_id is not None:
            self.progress.update(
                task_id,
                token_count=chunk.token_count,
                thinking_count=chunk.thinking_count,
            )

    def on_run_complete(self, context: RunContext, result) -> None:
        task_id = self.tasks.get(context.run_id)
        if task_id is not None:
            self.progress.update(
                task_id,
                description=f"Run {context.index + 1} Done",
                token_count=result.token_count,
                thinking_count=result.thinking_count,
            )
            self.progress.stop_task(task_id)

    def on_run_error(self, context: RunContext, exc: BaseException) -> None:
        task_id = self.tasks.get(context.run_id)
        if task_id is not None:
            self.progress.update(
                task_id,
                description=f"Run {context.index + 1} Error",
            )
            self.progress.stop_task(task_id)

    def on_synthesis_start(self) -> None:
        self.synthesis_task = self.progress.add_task(
            description="Synthesizing",
            start=True,
            token_count=0,
            thinking_count=0,
        )

    def on_synthesis_chunk(self, chunk) -> None:
        if self.synthesis_task is not None:
            self.progress.update(
                self.synthesis_task,
                token_count=chunk.token_count,
                thinking_count=chunk.thinking_count,
            )

    def on_synthesis_complete(self, result) -> None:
        if self.synthesis_task is not None:
            self.progress.update(
                self.synthesis_task,
                description="Synthesizing done",
                token_count=result.token_count,
                thinking_count=result.thinking_count,
            )
            self.progress.stop_task(self.synthesis_task)

    def on_synthesis_error(self, exc: BaseException) -> None:
        if self.synthesis_task is not None:
            self.progress.update(
                self.synthesis_task,
                description="Synthesizing error",
            )
            self.progress.stop_task(self.synthesis_task)

    def on_cancelled(self) -> None:
        for task_id in self.tasks.values():
            self.progress.update(task_id, description="Cancelled")
            self.progress.stop_task(task_id)
        if self.synthesis_task is not None:
            self.progress.update(self.synthesis_task, description="Cancelled")
            self.progress.stop_task(self.synthesis_task)


async def _execute(prompt: str, config: Config, trace_logger: Optional[TraceLogger]) -> ProcessorResult:
    progress_adapter = CLIProgress()
    hooks = progress_adapter.make_hooks()
    processor = Processor(config, hooks=hooks)

    progress_adapter.start()
    try:
        result = await processor.run(prompt, trace_logger=trace_logger)
    finally:
        progress_adapter.stop()

    return result


def _read_prompt(args) -> Optional[str]:
    prompt = args.prompt
    if prompt == "-":
        try:
            if sys.stdin.isatty():
                console.print("[yellow]Reading from stdin (press Ctrl+D when done):[/yellow]")
            prompt = sys.stdin.read().strip()
            if not prompt:
                console.print("[bold red]Error: no input received from stdin[/bold red]")
                return None
        except KeyboardInterrupt:
            console.print("\n[yellow]⏹️  输入已取消[/yellow]")
            return None
        except Exception as exc:  # pragma: no cover - defensive I/O
            console.print(f"[bold red]Error reading from stdin: {exc}[/bold red]")
            return None
    elif not prompt:
        console.print("[bold red]Error: prompt is required in CLI mode[/bold red]")
        return None
    return prompt


def _render_result(result: ProcessorResult) -> None:
    text = result.best_text()
    if text:
        console.print(Markdown(text))
    else:
        log_error("未收到任何模型输出")

    if result.interrupted:
        log_warning("任务在执行过程中被中断，以上输出来自已完成的部分运行")


def _summarize_trace(trace_logger: TraceLogger) -> None:
    if not trace_logger.enabled or not trace_logger.traces:
        return

    trace_file = trace_logger.save_traces()
    stats = trace_logger.get_stats()
    console.print(f"\n[bold green]轨迹已保存到: {trace_file}[/bold green]")
    console.print(
        f"[dim]统计信息: {stats['total_tasks']} 个任务, "
        f"成功率: {stats['success_rate']:.2%}, "
        f"总token: {stats['total_tokens']}, "
        f"平均耗时: {stats['avg_duration_ms']:.0f}ms[/dim]"
    )


def cli_main(args, config: Config) -> int:
    prompt = _read_prompt(args)
    if prompt is None:
        return 1

    trace_logger = create_trace_logger(
        config,
        enabled=config.trace_enabled,
        compact_mode=config.trace_compact,
    )

    try:
        result = anyio.run(_execute, prompt, config, trace_logger)
        _render_result(result)
        if trace_logger:
            _summarize_trace(trace_logger)
        return 0
    except (KeyboardInterrupt, anyio.get_cancelled_exc_class()):
        console.print("\n[yellow]⏹️  任务已中断，正在清理资源...[/yellow]")
        return 0
    except Exception as exc:  # pragma: no cover - defensive
        console.print(f"[bold red]Error: {exc}[/bold red]")
        return 1
