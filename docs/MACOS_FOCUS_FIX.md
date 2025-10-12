# macOS Desktop Focus Fix - Technical Documentation

## 问题概述

LLM Pro Mode 的 Tauri 桌面应用在 macOS 上启动后，窗口虽然可见并可以点击，但键盘输入无法直接生效，必须先点击其他应用再点回来才能输入。

## 根本原因分析

### macOS 焦点链机制

macOS 的键盘输入遵循三级焦点链：

```
Active App (活跃应用) → Key Window (主窗口) → First Responder (第一响应者)
```

**问题核心**：Tauri 的 `window.set_focus()` 只处理了 **Key Window → First Responder** 这两级，但没有激活 **App 本身**。

### 具体技术原因

1. **ActivationPolicy 不足**
   - 设置 `ActivationPolicy::Regular` 只是告诉系统"这个 App 可以成为活跃应用"
   - 但不会主动激活它

2. **窗口显示时机问题**
   - 在 `setup()` 阶段显示窗口时，NSApplication 事件循环还未完全就绪
   - WebKit 导航会被拦截（WebFramePolicyListenerProxy::ignore）
   - 导致焦点设置时机不对

3. **缺少强制激活调用**
   - 需要显式调用 `NSApp().activateIgnoringOtherApps_(YES)`
   - 这是唯一能强制将 App 带到前台并激活的方法

## 解决方案

### 1. 添加 macOS 原生 API 依赖

**文件**: `desktop/src-tauri/Cargo.toml`

```toml
[target.'cfg(target_os = "macos")'.dependencies]
cocoa = "0.25"
objc = "0.2"
```

### 2. 实现强制激活命令

**文件**: `desktop/src-tauri/src/lib.rs`

```rust
#[cfg(target_os = "macos")]
#[tauri::command]
fn force_activate(app: AppHandle) -> Result<(), String> {
    use tauri::ActivationPolicy;

    // 1. 设置激活策略为 Regular
    app.set_activation_policy(ActivationPolicy::Regular)
        .map_err(|e| e.to_string())?;

    // 2. 强制激活应用（关键！）
    unsafe {
        use cocoa::appkit::{NSApp, NSApplication};
        use cocoa::base::YES;
        NSApp().activateIgnoringOtherApps_(YES);
    }

    eprintln!("[Desktop] App forcefully activated");
    Ok(())
}
```

**技术要点**：
- `activateIgnoringOtherApps_(YES)` 是关键调用
- 必须使用 `unsafe` 块调用 Objective-C API
- 使用 `cocoa` crate 的 FFI 绑定

### 3. 调整窗口初始状态

**文件**: `desktop/src-tauri/tauri.conf.json`

```json
{
  "app": {
    "windows": [{
      "label": "main",
      "title": "LLM Pro Mode Desktop",
      "width": 1280,
      "height": 800,
      "visible": false  // 初始隐藏，避免时机问题
    }]
  }
}
```

### 4. 在正确时机激活窗口

**关键改变**：从 `setup()` 移到 `RunEvent::Ready`

```rust
.run(|app_handle, event| {
    use tauri::RunEvent;
    match event {
        RunEvent::Ready | RunEvent::Resumed => {
            eprintln!("[Desktop] RunEvent::Ready - activating and showing window");

            if let Some(window) = app_handle.get_webview_window("main") {
                // 正确的激活序列（顺序很重要！）

                // 1. 强制激活应用（带到前台）
                #[cfg(target_os = "macos")]
                {
                    if let Err(e) = force_activate(app_handle.clone()) {
                        eprintln!("[Desktop] Warning: Failed to force activate: {}", e);
                    }
                }

                // 2. 显示窗口
                if let Err(e) = window.show() {
                    eprintln!("[Desktop] Warning: Failed to show window: {}", e);
                } else {
                    eprintln!("[Desktop] Window shown");
                }

                // 3. 设置窗口焦点
                if let Err(e) = window.set_focus() {
                    eprintln!("[Desktop] Warning: Failed to set focus: {}", e);
                } else {
                    eprintln!("[Desktop] Window focused");
                }
            }
        }
        RunEvent::Exit | RunEvent::ExitRequested { .. } => {
            shutdown_backend(app_handle);
        }
        _ => {}
    }
})
```

### 5. 前端焦点管理增强

**文件**: `llm_pro_mode/interfaces/static/index.html`

```javascript
<script>
    // 检测是否在 Tauri 桌面环境
    if (window.__TAURI__ || window.__LLM_PRO_DESKTOP__) {
        console.log('[Desktop] Tauri environment detected, initializing focus management');

        const ensureFocus = () => {
            console.log('[Desktop] Ensuring window focus');
            window.focus();

            // 聚焦到消息输入框
            const messageInput = document.getElementById('message-input');
            if (messageInput) {
                setTimeout(() => {
                    messageInput.focus();
                    console.log('[Desktop] Input field focused');
                }, 100);
            }
        };

        // 页面加载时聚焦
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', ensureFocus);
        } else {
            ensureFocus();
        }

        // 页面可见时重新聚焦
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                console.log('[Desktop] Page visible, restoring focus');
                ensureFocus();
            }
        });
    }
</script>
```

## 技术细节

### 为什么必须在 RunEvent::Ready 执行？

1. **NSApplication 事件循环就绪**
   - `Ready` 事件表示 macOS 事件循环已完全启动
   - 此时 `activateIgnoringOtherApps` 才能正常工作

2. **避免 WebKit 导航拦截**
   - 在 `setup()` 阶段，WebKit 可能拦截导航
   - `Ready` 时导航已完成，状态稳定

3. **窗口管理器就绪**
   - macOS 窗口管理器在 `Ready` 时已完全初始化
   - 窗口显示和焦点设置更可靠

### 激活序列为什么重要？

```
activateIgnoringOtherApps → show → setFocus
```

**必须按此顺序**：
1. 先激活 App（否则窗口无法成为 Key Window）
2. 再显示窗口（此时 App 已活跃，窗口能正确获得焦点）
3. 最后设置焦点（完成 Key Window → First Responder 链）

### objc msg_send 的使用

```rust
use cocoa::base::id;
use objc::{msg_send, sel, sel_impl};

let app: id = NSApp();
let is_active: bool = msg_send![app, isActive];
```

- Rust 没有 `isActive()` 方法，必须用 `msg_send!` 宏
- 这是 Objective-C 消息传递机制的 FFI 调用
- `sel!` 宏生成选择器（selector）

## 验证方法

启动应用后检查日志输出：

```
[Desktop] macOS activation policy set to Regular
[Desktop] Web UI loaded, waiting for Ready event to show/focus
[Desktop] RunEvent::Ready - activating and showing window
[Desktop] App forcefully activated
[Desktop] Window shown
[Desktop] Window focused
```

**成功标志**：
- ✅ 窗口出现后可以**直接输入**，无需点击
- ✅ 窗口标题栏高亮显示（表示是活跃窗口）
- ✅ 输入框自动获得焦点

## 相关文件清单

### 修改的文件

1. **desktop/src-tauri/Cargo.toml** - 添加 cocoa/objc 依赖
2. **desktop/src-tauri/tauri.conf.json** - 窗口初始隐藏
3. **desktop/src-tauri/src/lib.rs** - 核心激活逻辑
4. **llm_pro_mode/interfaces/static/index.html** - 前端焦点管理

### 关键代码位置

- 强制激活函数: `lib.rs:184-198`
- 激活序列: `lib.rs:272-297`
- 前端焦点增强: `index.html:14-58`

## 平台差异说明

此修复**仅针对 macOS**：
- Windows/Linux 不需要 `activateIgnoringOtherApps`
- 使用 `#[cfg(target_os = "macos")]` 条件编译
- 其他平台使用默认 Tauri 行为

## 参考资源

- [macOS NSApplication 文档](https://developer.apple.com/documentation/appkit/nsapplication)
- [Tauri Window Management](https://tauri.app/v2/reference/javascript/api/window/)
- [cocoa-rs FFI 绑定](https://github.com/servo/core-foundation-rs)

## 总结

**核心问题**：macOS 三级焦点链未完全激活
**核心解决方案**：在 `RunEvent::Ready` 时序中调用 `activateIgnoringOtherApps_(YES)`
**关键时机**：必须等 NSApplication 事件循环就绪
**激活顺序**：App 激活 → 窗口显示 → 焦点设置

这个修复确保了桌面应用在 macOS 上的用户体验与原生应用一致。
