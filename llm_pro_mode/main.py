"""Main entry point for LLM Pro Mode application."""

import argparse
import uvicorn
import sys
from pathlib import Path

from .config import config, console
from .interfaces.cli import cli_main
from .interfaces.tui import tui_main
from .interfaces.api import app
from .tracing.logger import TraceLogger


def setup_argument_parser():
    """Set up command-line argument parser with detailed help."""
    parser = argparse.ArgumentParser(
        description="LLM Pro Mode - Multi-interface LLM completion tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用模式 (Usage Modes):

1. CLI模式 (CLI Mode) - 命令行直接执行:
   llm-pro-mode --prompt "解释什么是机器学习" --model "gpt-4"
   llm-pro-mode -p "写一个Python排序函数" -m "claude-3-sonnet" -n 5

2. TUI模式 (TUI Mode) - 交互式终端界面:
   llm-pro-mode --tui
   llm-pro-mode --tui --n_runs 5 --trace

3. 服务器模式 (Server Mode) - Web API服务:
   llm-pro-mode --serve --port 8080
   curl -X POST http://localhost:8080/completion \\
        -H "Content-Type: application/json" \\
        -d '{"prompt": "Hello world", "n_runs": 3}'

环境变量 (Environment Variables):
   export LLM_PRO_MODEL="gpt-4"
   export LLM_PRO_API_BASE="https://api.openai.com/v1"
   export LLM_PRO_API_KEY="your-api-key"

调试追踪 (Debug Tracing):
   --trace              启用完整调试追踪
   --trace_compact      启用简化调试追踪
   --trace_dir traces   指定追踪文件保存目录

TUI快捷键 (TUI Hotkeys):
   Ctrl+J              提交输入
   Ctrl+L              清空结果
   Ctrl+C/Q            退出程序
   Ctrl+A/E            行首/行尾
   ↑↓/PgUp/PgDn       滚动结果

示例配置文件 (.env):
   LLM_PRO_MODEL=gpt-4
   LLM_PRO_API_BASE=https://api.openai.com/v1
   LLM_PRO_API_KEY=sk-your-key-here
        """
    )

    # Model and API configuration
    model_group = parser.add_argument_group('模型配置 (Model Configuration)')
    model_group.add_argument(
        "--model", "-m",
        type=str,
        help="LLM模型名称 (如: gpt-4, claude-3-sonnet, deepseek-chat)"
    )
    model_group.add_argument(
        "--api_base", "-b",
        type=str,
        help="API基础URL (如: https://api.openai.com/v1)"
    )
    model_group.add_argument(
        "--api_key", "-k",
        type=str,
        help="API密钥"
    )

    # Execution parameters
    exec_group = parser.add_argument_group('执行参数 (Execution Parameters)')
    exec_group.add_argument(
        "--prompt", "-p",
        type=str,
        help="输入提示词 (仅CLI模式)"
    )
    exec_group.add_argument(
        "--n_runs", "-n",
        type=int,
        default=3,
        help="并行运行次数 (默认: 3)"
    )

    # Interface mode selection
    mode_group = parser.add_argument_group('界面模式 (Interface Modes)')
    mode_group.add_argument(
        "--serve",
        action="store_true",
        help="启动FastAPI服务器模式"
    )
    mode_group.add_argument(
        "--tui",
        action="store_true",
        help="启动终端用户界面模式"
    )
    mode_group.add_argument(
        "--port", "-P",
        type=int,
        default=8000,
        help="服务器端口 (默认: 8000)"
    )

    # Debug and tracing
    debug_group = parser.add_argument_group('调试追踪 (Debug & Tracing)')
    debug_group.add_argument(
        "--trace", "-t",
        action="store_true",
        help="启用调试追踪记录"
    )
    debug_group.add_argument(
        "--trace_dir",
        type=str,
        default="traces",
        help="追踪文件保存目录 (默认: traces)"
    )
    debug_group.add_argument(
        "--trace_compact", "--tc",
        action="store_true",
        help="使用简化追踪模式（仅关键信息）",
    )

    return parser


def main():
    """Main application entry point."""
    parser = setup_argument_parser()
    args = parser.parse_args()

    # Update configuration from command line arguments
    config.update_from_args(args)

    # Set up trace logging if requested
    if args.trace:
        # Just show info, actual trace loggers will be created as needed
        trace_dir = Path(args.trace_dir)
        trace_dir.mkdir(exist_ok=True)
        mode_text = "简化模式" if args.trace_compact else "完整模式"
        console.print(
            f"[bold yellow]轨迹记录已启用 ({mode_text})，保存到: {args.trace_dir}/[/bold yellow]"
        )

    # Display configuration
    api_key_display = f"{config.api_key[:5]}..." if config.api_key else "None"
    console.print(
        f"Model: {config.model_name}, API Base: {config.api_base}, "
        f"API Key: {api_key_display}"
    )

    # Route to appropriate interface
    if args.serve:
        console.print(f"[bold green]Starting FastAPI server on port {config.port}[/bold green]")
        uvicorn.run(app, host="0.0.0.0", port=config.port)
        return 0
    elif args.tui:
        console.print("[bold green]Starting Terminal UI mode[/bold green]")
        return tui_main(args)
    else:
        console.print("[bold green]Running CLI mode[/bold green]")
        return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())