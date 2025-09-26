"""Command-line interface functionality."""

import anyio
from rich.markdown import Markdown

from ..core.processor import main
from ..config import console
from ..tracing.logger import TraceLogger


async def run_cli(prompt: str, n_runs: int, trace_logger: TraceLogger = None):
    """Run CLI mode with progress bars."""
    result = await main(prompt, n_runs, show_progress=True, trace_logger=trace_logger)
    if result:
        console.print(Markdown(result))
    else:
        console.print("[bold red]No result received[/bold red]")


def cli_main(args):
    """Main CLI entry point."""
    if not args.prompt:
        console.print("[bold red]Error: prompt is required in CLI mode[/bold red]")
        return 1

    # Create trace logger if enabled
    trace_logger = None
    if args.trace:
        trace_logger = TraceLogger(
            trace_dir=args.trace_dir,
            enabled=True,
            compact_mode=args.trace_compact,
        )

    try:
        anyio.run(run_cli, args.prompt, args.n_runs, trace_logger)
        return 0
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        return 1