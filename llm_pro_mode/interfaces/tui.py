"""Terminal User Interface for LLM Pro Mode."""

import signal
import sys
from textual.app import App, ComposeResult
from textual.containers import Vertical, Container, ScrollableContainer
from textual.widgets import RichLog, Static, ProgressBar, Label, TextArea
from textual.binding import Binding
from textual import events
from rich.text import Text
from rich.markdown import Markdown

from ..config import Config
from ..core.processor import Processor, ProcessorHooks, RunContext, ProcessorResult
from ..core.llm_client import LLMChunk, LLMResult
from ..tracing.logger import TraceLogger
from .support import create_trace_logger


class LLMProTUI(App):
    """Terminal User Interface for LLM Pro Mode"""

    TITLE = "LLM Pro Mode - Terminal UI"
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #results-container {
        height: 68%;
        border: round $primary;
        background: $surface;
        margin: 0 1;
        padding: 1;
    }

    #progress-container {
        height: 20%;
        border: round $secondary;
        background: $surface;
        margin: 0 1;
        padding: 1;
    }

    #progress-scroll {
        height: 100%;
        background: transparent;
    }

    Label {
        margin: 0;
        height: 1;
        color: $text;
        background: transparent;
    }

    ProgressBar {
        margin: 0;
        height: 1;
        color: $success;
        background: $surface-lighten-1;
    }

    #input-container {
        height: 12%;
        margin: 0 1;
        padding: 0;
        background: transparent;
    }

    #results-log {
        height: 100%;
        scrollbar-gutter: stable;
        scrollbar-size: 1 1;
        background: transparent;
        color: $text;
        overflow: auto;
        text-wrap: wrap;
    }

    #prompt-input {
        width: 100%;
        height: 100%;
        border: round $accent;
        background: $surface-lighten-1;
        color: $text;
        padding: 1;
        scrollbar-size: 0 1;
    }

    Static {
        background: transparent;
        color: $text-muted;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear", "Clear Results"),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("page_up", "scroll_page_up", "Page Up", show=False),
        Binding("page_down", "scroll_page_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Scroll to Top", show=False),
        Binding("end", "scroll_end", "Scroll to Bottom", show=False),
        # Emacs-style bindings for text input
        Binding("ctrl+j", "submit_prompt", "Submit Prompt", show=False),
        Binding("enter", "newline", "New Line", show=False),
        Binding("ctrl+a", "cursor_line_start", "Line Start", show=False),
        Binding("ctrl+e", "cursor_line_end", "Line End", show=False),
        Binding("ctrl+p", "cursor_up", "Previous Line", show=False),
        Binding("ctrl+n", "cursor_down", "Next Line", show=False),
        Binding("ctrl+b", "cursor_left", "Backward Char", show=False),
        Binding("ctrl+f", "cursor_right", "Forward Char", show=False),
        Binding("ctrl+k", "delete_line", "Kill Line", show=False),
        Binding("ctrl+d", "delete_right", "Delete Right", show=False),
        Binding("ctrl+h", "delete_left", "Delete Left", show=False),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.n_runs = config.n_runs
        self.enable_trace = config.trace_enabled
        self.trace_compact = config.trace_compact
        self.current_tasks = {}  # Store task progress info: {task_name: {"progress": ProgressBar, "label": Label}}
        self.results_log = None
        self.progress_container = None
        self.prompt_input = None

    def compose(self) -> ComposeResult:
        """Create the UI layout"""
        with Vertical():
            # Results panel (top, largest)
            with Static("📝 Chat Results", id="results-container"):
                yield RichLog(id="results-log")

            # Progress panel (middle)
            with Static("⚡ Task Progress", id="progress-container"):
                yield ScrollableContainer(id="progress-scroll")

            # Input panel (bottom)
            with Container(id="input-container"):
                yield TextArea(placeholder="💬 Enter your prompt here... (Ctrl+J to submit)", id="prompt-input")

    def on_mount(self) -> None:
        """Initialize widgets after mounting"""
        self.results_log = self.query_one("#results-log", RichLog)
        self.progress_container = self.query_one("#progress-scroll", ScrollableContainer)
        self.prompt_input = self.query_one("#prompt-input", TextArea)

        # Focus on input
        self.prompt_input.focus()

        # Welcome message with proper Rich formatting
        title = Text("🚀 LLM Pro Mode TUI", style="bold cyan")
        self.results_log.write(title)
        self.results_log.write("")

        tip1 = Text("💡 Press Ctrl+J to submit, Enter for new line", style="dim")
        self.results_log.write(tip1)

        tip2 = Text("⌨️  Emacs: Ctrl+A/E, Ctrl+P/N, Ctrl+K", style="dim")
        self.results_log.write(tip2)

        tip3 = Text("🚪 Ctrl+C/Q to quit • 📜 ↑↓/PgUp/PgDn to scroll • 🧹 Ctrl+L to clear", style="dim")
        self.results_log.write(tip3)

        tip4 = Text("💡 Esc: Clear input or close popups (smart handling)", style="dim")
        self.results_log.write(tip4)

        self.results_log.write("")
        if self.enable_trace:
            mode_text = "简化模式" if self.trace_compact else "完整模式"
            trace_msg = Text(f"🔍 轨迹记录已启用 ({mode_text})", style="yellow")
            self.results_log.write(trace_msg)

        # Set up signal handlers for clean exit
        def signal_handler(signum, frame):
            try:
                self.exit(0)
            except:
                sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _task_name(self, context: RunContext) -> str:
        return f"Run {context.index + 1}"

    def _build_hooks(self) -> ProcessorHooks:
        return ProcessorHooks(
            run_start=self._on_run_start,
            run_chunk=self._on_run_chunk,
            run_complete=self._on_run_complete,
            run_error=self._on_run_error,
            synthesis_start=self._on_synthesis_start,
            synthesis_chunk=self._on_synthesis_chunk,
            synthesis_complete=self._on_synthesis_complete,
            synthesis_error=self._on_synthesis_error,
            cancelled=self._on_cancelled,
        )

    def _on_run_start(self, context: RunContext) -> None:
        self.update_progress(self._task_name(context), "Starting")

    def _on_run_chunk(self, context: RunContext, chunk: LLMChunk) -> None:
        if chunk.kind == "thinking":
            details = f"{chunk.thinking_count} thinking tokens"
            self.update_progress(self._task_name(context), "Thinking", details)
        else:
            details = f"{chunk.token_count} tokens"
            self.update_progress(self._task_name(context), "Generating", details)

    def _on_run_complete(self, context: RunContext, result: LLMResult) -> None:
        status = f"Completed - {result.finish_reason or 'Done'}"
        details = f"{result.token_count} tokens, {result.thinking_count} thinking"
        self.update_progress(self._task_name(context), status, details)

    def _on_run_error(self, context: RunContext, exc: BaseException) -> None:
        self.update_progress(self._task_name(context), "Error", str(exc))

    def _on_synthesis_start(self) -> None:
        self.update_progress("Synthesis", "Combining results")

    def _on_synthesis_chunk(self, chunk: LLMChunk) -> None:
        if chunk.kind == "thinking":
            self.update_progress("Synthesis", "Thinking", f"{chunk.thinking_count} thinking")
        else:
            self.update_progress("Synthesis", "Generating", f"{chunk.token_count} tokens")

    def _on_synthesis_complete(self, result: LLMResult) -> None:
        details = f"{result.token_count} tokens, {result.thinking_count} thinking"
        self.update_progress("Synthesis", "Completed", details)

    def _on_synthesis_error(self, exc: BaseException) -> None:
        self.update_progress("Synthesis", "Error", str(exc))

    def _on_cancelled(self) -> None:
        for task_name in list(self.current_tasks.keys()):
            self.update_progress(task_name, "Interrupted")

    async def action_submit_prompt(self) -> None:
        """Handle prompt submission via Ctrl+J"""
        prompt = self.prompt_input.text.strip()
        if not prompt:
            return

        # Clear input
        self.prompt_input.clear()

        # Show user prompt in results
        user_msg = Text(f"\n🤔 User: {prompt}", style="bold blue")
        self.results_log.write(user_msg)

        processing_msg = Text("⏳ Processing...", style="yellow")
        self.results_log.write(processing_msg)

        # Clear existing progress bars and create new ones
        self.n_runs = self.config.n_runs
        self.clear_progress_tasks()
        self.create_progress_tasks()

        trace_logger = create_trace_logger(
            self.config,
            enabled=self.enable_trace,
            compact_mode=self.trace_compact,
        )

        processor = Processor(self.config, hooks=self._build_hooks())

        try:
            result = await processor.run(prompt, trace_logger=trace_logger)
            self._display_result(result)
            if trace_logger:
                self._display_trace_info(trace_logger)
        except Exception as exc:
            error_msg = Text(f"❌ Error: {str(exc)}", style="bold red")
            self.results_log.write(error_msg)

        finally:
            # Clear progress bars after completion
            self.set_timer(2.0, lambda: self.clear_progress_tasks())  # Clear after 2 seconds

    def clear_progress_tasks(self):
        """Clear all progress bars"""
        if self.progress_container:
            for task_info in self.current_tasks.values():
                if "label" in task_info:
                    task_info["label"].remove()
                if "progress" in task_info:
                    task_info["progress"].remove()
            self.current_tasks.clear()

    def create_progress_tasks(self):
        """Create progress bars for all tasks"""
        if not self.progress_container:
            return

        # Create progress bars for each run + synthesis
        for i in range(self.n_runs):
            task_name = f"Run {i + 1}"
            self.add_task_progress(task_name)

        # Add synthesis task
        self.add_task_progress("Synthesis")

    def add_task_progress(self, task_name: str):
        """Add a progress bar for a specific task"""
        if not self.progress_container or task_name in self.current_tasks:
            return

        # Create label and progress bar
        label = Label(f"{task_name}: Ready")
        progress_bar = ProgressBar(total=100, show_eta=False)
        progress_bar.progress = 0

        # Add to container
        self.progress_container.mount(label)
        self.progress_container.mount(progress_bar)

        # Store references
        self.current_tasks[task_name] = {
            "label": label,
            "progress": progress_bar,
            "status": "Ready"
        }

    def update_progress(self, task_name: str, status: str, details: str = ""):
        """Update progress display for a specific task"""
        if task_name not in self.current_tasks:
            return

        task_info = self.current_tasks[task_name]

        # Update label text
        label_text = f"{task_name}: {status}"
        if details:
            label_text += f" - {details}"

        task_info["label"].update(label_text)
        task_info["status"] = status

        # Update progress bar based on status with visual feedback
        if status == "Starting":
            task_info["progress"].progress = 10
        elif status == "Receiving response":
            task_info["progress"].progress = 25
        elif status == "Thinking":
            task_info["progress"].progress = 50
        elif status == "Generating":
            task_info["progress"].progress = 85
        elif status.startswith("Completed"):
            task_info["progress"].progress = 100
        elif status == "Error":
            task_info["progress"].progress = 0  # Reset on error
            # Change color to red for errors
            task_info["progress"].styles.color = "red"
        elif status == "Combining results":
            task_info["progress"].progress = 60
        elif status == "Completed":
            task_info["progress"].progress = 100

    def _display_result(self, result: ProcessorResult) -> None:
        if not self.results_log:
            return

        output = result.best_text()
        if output:
            assistant_header = Text("\n🤖 Assistant:", style="bold green")
            self.results_log.write(assistant_header)
            self.results_log.write(Markdown(output))
        else:
            self.results_log.write(Text("❌ No result received", style="red"))

        failures = [run for run in result.runs if run.error]
        if failures:
            warning_msg = Text(
                f"⚠️  {len(failures)} runs encountered errors", style="yellow"
            )
            self.results_log.write(warning_msg)

        if result.interrupted:
            interrupted_msg = Text(
                "⚠️  任务被中断，已返回部分结果", style="yellow"
            )
            self.results_log.write(interrupted_msg)

    def _display_trace_info(self, trace_logger: TraceLogger) -> None:
        if not self.results_log or not trace_logger.enabled or not trace_logger.traces:
            return

        stats = trace_logger.get_stats()
        trace_info = (
            f"📊 Debug Info: {stats['total_tasks']} tasks, "
            f"成功率: {stats['success_rate']:.2%}, "
            f"总token: {stats['total_tokens']}, "
            f"平均耗时: {stats['avg_duration_ms']:.0f}ms"
        )
        debug_msg = Text(trace_info, style="dim")
        self.results_log.write(debug_msg)

    def add_result(self, text: str, is_markdown: bool = False):
        """Add content to results log"""
        if self.results_log:
            if is_markdown:
                self.results_log.write(Markdown(text))
            else:
                self.results_log.write(text)

    def action_clear(self) -> None:
        """Clear the results log"""
        if self.results_log:
            self.results_log.clear()
            clear_msg = Text("🧹 Results Cleared", style="bold yellow")
            self.results_log.write(clear_msg)

    def action_scroll_up(self) -> None:
        """Scroll results log up"""
        if self.results_log:
            self.results_log.scroll_relative(y=-1)

    def action_scroll_down(self) -> None:
        """Scroll results log down"""
        if self.results_log:
            self.results_log.scroll_relative(y=1)

    def action_scroll_page_up(self) -> None:
        """Scroll results log page up"""
        if self.results_log:
            self.results_log.scroll_relative(y=-10)

    def action_scroll_page_down(self) -> None:
        """Scroll results log page down"""
        if self.results_log:
            self.results_log.scroll_relative(y=10)

    def action_scroll_home(self) -> None:
        """Scroll results log to top"""
        if self.results_log:
            self.results_log.scroll_home()

    def action_scroll_end(self) -> None:
        """Scroll results log to bottom"""
        if self.results_log:
            self.results_log.scroll_end()

    def action_newline(self) -> None:
        """Insert a new line in the text area"""
        if self.prompt_input:
            self.prompt_input.insert("\n")

    def action_cursor_line_start(self) -> None:
        """Move cursor to start of current line (Ctrl+A)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_line_start()

    def action_cursor_line_end(self) -> None:
        """Move cursor to end of current line (Ctrl+E)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_line_end()

    def action_cursor_up(self) -> None:
        """Move cursor up one line (Ctrl+P)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_up()

    def action_cursor_down(self) -> None:
        """Move cursor down one line (Ctrl+N)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_down()

    def action_cursor_left(self) -> None:
        """Move cursor left one character (Ctrl+B)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_left()

    def action_cursor_right(self) -> None:
        """Move cursor right one character (Ctrl+F)"""
        if self.prompt_input:
            self.prompt_input.action_cursor_right()

    def action_delete_line(self) -> None:
        """Delete from cursor to end of line (Ctrl+K)"""
        if self.prompt_input:
            self.prompt_input.action_delete_line()

    def action_delete_right(self) -> None:
        """Delete character to the right of cursor (Ctrl+D)"""
        if self.prompt_input:
            self.prompt_input.action_delete_right()

    def action_delete_left(self) -> None:
        """Delete character to the left of cursor (Ctrl+H)"""
        if self.prompt_input:
            self.prompt_input.action_delete_left()

    def action_quit(self) -> None:
        """Quit the application"""
        self.exit(0)

    def on_key(self, event: events.Key) -> None:
        """Handle key events with focus-aware logic"""
        if event.key == "ctrl+c":
            self.action_quit()
        elif event.key == "ctrl+q":
            self.action_quit()
        elif event.key == "escape":
            # Only quit if we're in the main interface and input has focus
            # If there's a modal or popup, let it handle the escape key first
            self.action_smart_escape()

    def action_smart_escape(self) -> None:
        """Smart escape handling based on current state"""
        # Check if there are any modal screens or layers active
        # In Textual, we can check the app's screen stack
        try:
            if hasattr(self, '_screen_stack') and len(self._screen_stack) > 1:
                # There's a modal/popup active, let the default handler take care of it
                return
        except:
            # If we can't check screen stack, continue with other logic
            pass

        # Check if input field has focus and has content
        if self.prompt_input and hasattr(self.prompt_input, 'has_focus') and self.prompt_input.has_focus:
            if self.prompt_input.text.strip():
                # Input has content, clear it instead of quitting
                self.prompt_input.clear()
                return

        # Check if any widget other than our main widgets has focus
        focused_widget = self.focused
        if focused_widget and focused_widget not in [self.prompt_input, self.results_log]:
            # Some other widget has focus (like a modal or popup)
            # Let the default escape handling work
            return

        # Default behavior: quit the application
        self.action_quit()

    def check_action_enabled(self, action: str) -> bool:
        """Ensure quit action is always enabled"""
        if action == "quit":
            return True
        return super().check_action_enabled(action)


def tui_main(config: Config) -> int:
    """Main TUI entry point."""
    tui_app = LLMProTUI(config)
    try:
        tui_app.run()
        return 0
    except KeyboardInterrupt:
        print("\n👋 LLM Pro Mode TUI exited")
        return 0
    except Exception as e:
        print(f"\n❌ TUI Error: {e}")
        return 1
