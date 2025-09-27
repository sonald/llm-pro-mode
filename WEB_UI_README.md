# LLM Pro Mode - Web UI 模式使用指南

## 概述

LLM Pro Mode 现在支持第四种执行模式：**Web UI 模式**，提供类似 ChatGPT 的现代化网页界面，集成实时任务监控功能。

## ✨ 核心特性

### 1. ChatGPT 风格界面
- 消息气泡式对话界面
- 流式响应显示
- 对话历史记录
- 响应式设计支持移动端

### 2. 实时任务监控
- 显示所有并行任务的进度状态
- 可交互的任务卡片
- 点击查看详细信息（推理过程、内容等）
- 实时进度条和状态更新

### 3. 现代化用户体验
- 深色/浅色主题自动切换
- 平滑动画和过渡效果
- WebSocket 实时通信
- 性能统计面板

## 🚀 快速开始

### 安装依赖
```bash
pip install -e .
```

### 启动 Web UI 模式
```bash
llm-pro-mode --web --port 8000
```

然后在浏览器中打开：`http://localhost:8000`

## 📱 界面布局

```
┌─────────────────────────────────────────────────────────────┐
│  LLM Pro Mode - Web Interface                    [Settings] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Chat Interface (70%)           │  Task Monitor (30%)       │
│  ┌─────────────────────────────┐│  ┌─────────────────────────┐│
│  │  💭 User: 解释机器学习      ││  │  🔄 Tasks in Progress   ││
│  │                             ││  │  ┌─ Run 1: Thinking... ─┐││
│  │  🤖 Assistant:             ││  │  │ ▓▓▓▓▓░░░░░ 50%       │││
│  │  机器学习是一种...          ││  │  └──────────────────────┘││
│  │                             ││  │  ┌─ Run 2: Generating.. ─┐││
│  │  [推理过程...]              ││  │  │ ▓▓▓▓▓▓▓░░░ 70%      │││
│  │                             ││  │  └──────────────────────┘││
│  │                             ││  │  ┌─ Run 3: Completed ✓─┐ ││
│  │                             ││  │  │ ▓▓▓▓▓▓▓▓▓▓ 100%     │││
│  │                             ││  │  └──────────────────────┘││
│  │                             ││  │                         ││
│  └─────────────────────────────┘│  │  📊 Statistics          ││
│  ┌─────────────────────────────┐│  │  • Total: 156 tokens   ││
│  │ 在这里输入消息...           ││  │  • Time: 2.3s          ││
│  │                       [发送]││  │  • Success: 100%       ││
│  └─────────────────────────────┘│  └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## 🖥️ 桌面应用封装 (Tauri)

Tauri 版本会自动启动并管理本地 FastAPI 服务, 将 Web UI 包装成原生桌面程序。

### 先决条件
- Rust (2021 edition) 与 `cargo`
- `tauri-cli` (`cargo install tauri-cli`)
- Python 环境可通过 `python3` 或设置 `LLM_PRO_PYTHON` 指定

### 开发模式
```bash
cd desktop
cargo tauri dev
```
运行后窗口会自动打开, 后端服务绑定 `http://127.0.0.1:<动态端口>`。

### 打包发布
```bash
cd desktop
cargo tauri build
```
构建产物位于 `desktop/src-tauri/target/release/bundle/` 下, 可用于分发。

> 提示: 关闭桌面应用时, Tauri 会自动结束内置的 Python 后端进程, 无需手动清理。

## 💡 使用指南

### 基本操作
1. **发送消息**：在输入框中输入问题，按 `Ctrl+J` 或点击发送按钮
2. **设置参数**：选择并行运行次数（3、5、7、10）
3. **启用追踪**：勾选 "Enable Trace" 获取详细调试信息
4. **查看进度**：右侧面板实时显示任务进度

### 任务监控功能
- **进度卡片**：显示每个任务的状态和进度百分比
- **状态指示器**：
  - 🔄 Running - 任务进行中
  - ✅ Completed - 任务已完成
  - ❌ Failed - 任务失败
- **详情查看**：点击任务卡片查看详细信息
  - 🤔 Thinking - 推理过程
  - 📝 Content - 输出内容
  - 🔍 Metadata - 元数据信息

### 快捷键
- `Ctrl+J` - 发送消息
- `Ctrl+L` - 清空聊天记录
- `Ctrl+C/Q` - 退出（需在终端中）
- `Escape` - 关闭弹窗

## 🔧 技术架构

### 前端技术栈
- **HTML5** - 语义化标记
- **CSS3** - 现代样式和动画
- **JavaScript (ES6+)** - 原生 JavaScript，无外部依赖
- **WebSocket** - 实时双向通信

### 后端架构
- **FastAPI** - 高性能 Web 框架
- **WebSocket Manager** - 连接管理和消息广播
- **Progress Tracker** - 任务进度跟踪
- **Pydantic** - 数据验证和序列化

### 消息协议
```typescript
interface WebSocketMessage {
    type: 'task_started' | 'task_progress' | 'task_completed' |
          'synthesis_started' | 'synthesis_completed' | 'final_result' | 'error';
    task_id?: string;
    content?: string;
    progress?: number;
    thinking?: string;
    metadata?: object;
}
```

## 📂 文件结构

```
llm_pro_mode/
├── interfaces/
│   ├── web.py              # Web UI FastAPI 路由和 WebSocket 处理
│   └── static/             # 静态资源文件
│       ├── index.html      # 主界面 HTML
│       ├── style.css       # 样式文件
│       └── app.js          # 前端 JavaScript 逻辑
├── models/
│   └── schemas.py          # WebSocket 消息模型定义
└── core/
    ├── llm_client.py       # 新增流式处理函数
    └── processor.py        # 核心处理逻辑
```

## 🆚 四种模式对比

| 模式 | 界面类型 | 使用场景 | 特色功能 |
|------|----------|----------|----------|
| **CLI** | 命令行 | 脚本/自动化 | 管道支持、stdin 输入 |
| **TUI** | 终端界面 | 开发/调试 | 交互式操作、键盘导航 |
| **Web UI** | 网页界面 | 日常使用 | 任务监控、现代界面 |
| **Server** | API 服务 | 集成开发 | RESTful API、编程接口 |

## 🎨 主题和样式

### 自动主题切换
- 支持浅色和深色主题
- 根据系统偏好自动切换
- CSS 变量驱动的动态样式

### 响应式设计
- 桌面端：70/30 布局（聊天/监控）
- 移动端：垂直堆叠布局
- 自适应字体和间距

## 🔍 高级功能

### 调试和追踪
- 启用 `Enable Trace` 获取详细日志
- 查看每个任务的推理过程
- 性能统计和错误信息

### 流式推理兼容性说明
- 有些模型（例如 Grok 系列）会在流式响应中把推理内容以列表/字典形式返回。
- 后端会在发送给前端前自动将这些结构化 reasoning 正常化为纯文本，确保任务进度和合成阶段不会卡住。
- 如果增加新的模型适配，请确认其流式返回格式是否包含结构化字段，并保持上述归一化逻辑。

### 设置面板
- 模型配置
- API 参数设置
- 连接状态监控

### 错误处理
- 自动重连机制
- 优雅的错误提示
- 连接状态指示器

## 🚀 启动示例

```bash
# 基本启动
llm-pro-mode --web

# 指定端口
llm-pro-mode --web --port 8080

# 启用调试追踪
llm-pro-mode --web --trace

# 使用特定配置
llm-pro-mode --web --profile openai --n_runs 5
```

## 🤝 开发和贡献

### 开发环境设置
```bash
# 克隆仓库
git clone <repository-url>
cd llm-pro-mode

# 安装开发依赖
pip install -e .

# 启动开发服务器
llm-pro-mode --web --port 8000
```

### 自定义样式
编辑 `llm_pro_mode/interfaces/static/style.css` 来自定义界面样式。

### 扩展功能
- 添加新的 WebSocket 消息类型
- 扩展任务监控功能
- 集成更多 LLM 提供商

## 📋 待办事项

- [ ] 添加消息导出功能
- [ ] 支持文件上传
- [ ] 集成语音输入
- [ ] 添加快捷模板
- [ ] 支持多语言界面

---

🎉 **享受现代化的 LLM 交互体验！**
