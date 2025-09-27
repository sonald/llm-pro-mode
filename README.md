# LLM Pro Mode

LLM Pro Mode 是一个面向开发者的多界面大模型驱动工具，支持并行调用、结果综合、多种交互方式（CLI/TUI/Web UI/桌面端），并提供完善的配置与追踪能力，帮助你在不同场景快速完成 Prompt 调用与调试。

## ✨ 核心特性

- **多界面模式**：命令行、终端 UI、Web UI、API 服务器与 Tauri 桌面端随需切换
- **并行推理与综合**：支持一次发送多轮并行请求，并在后台自动综合生成高质量最终回答
- **实时任务监控**：Web UI/桌面端提供任务卡片、进度条、流式推理与统计面板
- **Profile 配置管理**：可保存多个模型/API 组合，随时切换并设置默认配置
- **可选追踪日志**：开启 `--trace` 后生成详细的推理/响应轨迹，便于调试与回溯

## 🚀 安装与环境准备

```bash
# 克隆代码后安装依赖
pip install -e .

# 可选：安装 tauri-cli（用于桌面封装）
cargo install tauri-cli
```

如需自定义 Python 解释器供 Tauri 使用，可设置 `LLM_PRO_PYTHON` 环境变量，例如：

```bash
export LLM_PRO_PYTHON="$HOME/.pyenv/versions/3.11.7/bin/python"
```

## 🧭 使用模式

### 1. CLI 模式

```bash
llm-pro-mode --prompt "写一个快速排序" --model "gpt-4"
llm-pro-mode -p "分析这段代码" -m "claude-3-sonnet" -n 5
llm-pro-mode -p - < input.txt           # 从 stdin 读取
```

### 2. TUI 模式

```bash
llm-pro-mode --tui
llm-pro-mode --tui --n_runs 5 --trace
```

### 3. Web UI 模式

```bash
llm-pro-mode --web --port 8000
# 浏览器访问 http://localhost:8000
```

Web UI 具备 ChatGPT 风格界面、实时任务面板、Profile 下拉选择器，并支持在设置里将 Profile 设为默认。

### 4. API 服务器模式

```bash
llm-pro-mode --serve --port 8080
curl -X POST http://localhost:8080/completion \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Hello", "n_runs": 3}'
```

### 5. 桌面应用（Tauri 封装）

```bash
cd desktop
cargo tauri dev      # 开发模式
cargo tauri build    # 构建发布包
```

桌面端会自动启动本地 FastAPI 后端，并在设置面板中提供与 Web UI 一致的 Profile 下拉选择器。

## 📁 目录结构

```
llm_pro_mode/
├── core/            # 核心调用、并行与综合逻辑
├── interfaces/      # CLI/TUI/Web/API 等界面实现
│   └── static/      # Web UI 静态资源 (HTML/CSS/JS)
├── models/          # Pydantic 模型与协议定义
├── tracing/         # 追踪与日志相关组件
├── desktop.py       # Tauri 桌面模式后端启动器
└── main.py          # 程序入口与参数解析
```

## 🔧 Profile 配置管理

支持通过 JSON 文件或命令管理不同的模型配置，常用命令如下：

```bash
llm-pro-mode --list-profiles
llm-pro-mode --show-profile openai
llm-pro-mode --save-profile my-groq
llm-pro-mode --delete-profile old-config
llm-pro-mode --set-default-profile claude
```

Profile 中的 `api_key` 字段可以直接填写环境变量名（如 `OPENAI_API_KEY`），运行时会自动解析。Web UI 与桌面端也会显示当前激活的 Profile，并允许一键切换/设为默认。

## 🛠️ 调试与追踪

- 通过 `--trace` 或 `--trace_compact` 开启详细/精简追踪日志，默认保存在 `traces/`
- 使用 `--trace_dir` 自定义追踪输出目录
- Web UI 在设置面板可勾选 “Enable Trace” 同步开启追踪
- `python -m compileall llm_pro_mode` 可快速检查语法问题

## 🧪 测试

项目使用 `pytest`，可直接运行：

```bash
pytest
```

如需异步测试支持，可使用 `pytest-asyncio`。

## 🤝 贡献指南

欢迎提交 Issue 或 Pull Request。在提交代码前请确保：

1. 所有必要的单元测试已通过
2. 如果新增/修改功能，请同步更新文档或 README
3. 遵循仓库现有的代码风格与注释规范

---

如有问题或建议，欢迎提 Issue 交流。希望 LLM Pro Mode 能帮助你更高效地使用大模型！
