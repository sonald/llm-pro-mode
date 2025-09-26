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

配置 Profile 管理 (Profile Management):
   llm-pro-mode --list-profiles                列出所有可用的配置
   llm-pro-mode --show-profile openai          显示指定配置的详细信息
   llm-pro-mode --profile openai --prompt "..."  使用指定配置运行
   llm-pro-mode --save-profile my-config       保存当前配置为新 profile
   llm-pro-mode --delete-profile old-config    删除指定配置
   llm-pro-mode --set-default-profile openai   设置默认配置

配置优先级 (Configuration Priority):
   1. 命令行参数 (Command line args)
   2. JSON配置文件 Profile (JSON profile)
   3. 环境变量 (Environment variables)
   4. 默认值 (Default values)

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

JSON配置文件示例 (config.json):
   {
     "default_profile": "grok",
     "profiles": {
       "grok": {
         "model_name": "x-ai/grok-2-vision-1212",
         "api_base": "https://openrouter.ai/api/v1",
         "api_key": "OPENROUTER_API_KEY",
         "description": "OpenRouter Grok Code 模型配置"
       },
       "openai": {
         "model_name": "gpt-4",
         "api_base": "https://api.openai.com/v1",
         "api_key": "OPENAI_API_KEY",
         "description": "OpenAI GPT-4 配置"
       }
     }
   }

API Key 环境变量引用 (Environment Variable Reference):
   配置文件中的 api_key 可以设置为环境变量名称，程序会自动解析：
   - "OPENROUTER_API_KEY" -> 从环境变量 OPENROUTER_API_KEY 读取实际 key
   - "OPENAI_API_KEY" -> 从环境变量 OPENAI_API_KEY 读取实际 key
   - "sk-proj-xxx..." -> 直接使用字面量作为 API Key

   安全优势：避免在配置文件中直接存储敏感的 API Key

示例配置文件 (.env):
   LLM_PRO_MODEL=gpt-4
   LLM_PRO_API_BASE=https://api.openai.com/v1
   LLM_PRO_API_KEY=sk-your-key-here
        """
    )

    # Profile configuration
    profile_group = parser.add_argument_group('配置文件 (Profile Configuration)')
    profile_group.add_argument(
        "--profile",
        type=str,
        help="使用指定的配置 profile"
    )
    profile_group.add_argument(
        "--config",
        type=str,
        help="指定配置文件路径"
    )
    profile_group.add_argument(
        "--list-profiles",
        action="store_true",
        help="列出所有可用的 profiles"
    )
    profile_group.add_argument(
        "--show-profile",
        type=str,
        metavar="NAME",
        help="显示指定 profile 的详细信息"
    )
    profile_group.add_argument(
        "--save-profile",
        type=str,
        metavar="NAME",
        help="将当前配置保存为新的 profile"
    )
    profile_group.add_argument(
        "--delete-profile",
        type=str,
        metavar="NAME",
        help="删除指定的 profile"
    )
    profile_group.add_argument(
        "--set-default-profile",
        type=str,
        metavar="NAME",
        help="设置默认 profile"
    )

    # Model and API configuration
    model_group = parser.add_argument_group('模型配置 (Model Configuration)')
    model_group.add_argument(
        "--model", "-m",
        type=str,
        help="LLM模型名称 (如: gpt-4, claude-3-sonnet, deepseek-chat) [覆盖 profile 设置]"
    )
    model_group.add_argument(
        "--api_base", "-b",
        type=str,
        help="API基础URL (如: https://api.openai.com/v1) [覆盖 profile 设置]"
    )
    model_group.add_argument(
        "--api_key", "-k",
        type=str,
        help="API密钥 [覆盖 profile 设置]"
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
    try:
        parser = setup_argument_parser()
        args = parser.parse_args()

        # Handle profile management commands first (these don't need full config)
        if args.list_profiles:
            from .profile_manager import ProfileManager
            manager = ProfileManager(args.config if hasattr(args, 'config') else None)
            manager.list_profiles()
            return 0

        if args.show_profile:
            from .profile_manager import ProfileManager
            manager = ProfileManager(args.config if hasattr(args, 'config') else None)
            manager.show_profile(args.show_profile)
            return 0

        if args.delete_profile:
            from .profile_manager import ProfileManager
            manager = ProfileManager(args.config if hasattr(args, 'config') else None)
            if manager.delete_profile(args.delete_profile):
                console.print(f"[green]Profile '{args.delete_profile}' 已删除[/green]")
            return 0

        if args.set_default_profile:
            from .profile_manager import ProfileManager
            manager = ProfileManager(args.config if hasattr(args, 'config') else None)
            if manager.set_default_profile(args.set_default_profile):
                console.print(f"[green]默认 profile 已设置为 '{args.set_default_profile}'[/green]")
            return 0

        # Update configuration from command line arguments
        config.update_from_args(args)

        # Handle save-profile command (needs full config)
        if args.save_profile:
            if config.save_current_as_profile(args.save_profile, f"Saved from command line"):
                console.print(f"[green]配置已保存为 profile '{args.save_profile}'[/green]")
            else:
                console.print(f"[red]保存 profile '{args.save_profile}' 失败[/red]")
            return 0

        # Set up trace logging if requested
        if args.trace:
            # Just show info, actual trace loggers will be created as needed
            trace_dir = Path(args.trace_dir)
            trace_dir.mkdir(exist_ok=True)
            mode_text = "简化模式" if args.trace_compact else "完整模式"
            console.print(
                f"[bold yellow]轨迹记录已启用 ({mode_text})，保存到: {args.trace_dir}/[/bold yellow]"
            )

        # Display configuration summary
        config_summary = config.get_effective_config_summary()
        console.print(f"[dim]配置: {config_summary}[/dim]")

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

    except KeyboardInterrupt:
        console.print("\n[yellow]👋 操作已取消，程序正常退出[/yellow]")
        return 0
    except Exception as e:
        console.print(f"\n[bold red]❌ 程序执行错误: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())