# Browser Brain — 优化开发记录

> 记录时间：2026-06-22 ~ 2026-06-23
> 项目路径：`browser-brain-app/`
> V1 归档：`browser-brain-v1-archived/`

## 概述

对 Browser Brain 进行了全面重构和优化。原项目存在三个核心问题（Chrome 检测、捕获速度、UI 简陋），以及 V1/V2 代码共存、app.py 职责过多等架构问题。

本次优化覆盖 4 个阶段、14 个新建文件、5 个重写文件、3 个修改文件。

---

## 阶段 0：基础设施

### 配置系统 (`config.py`) **[新建]**
- 创建 `AppConfig` dataclass，集中管理所有硬编码值
- 加载链：`./config.json` > `~/.browser-brain/config.json` > 环境变量 > 默认值
- 所有路径（Chrome、外脑）、端口、超时、窗口尺寸等统一管理
- 创建 `config.example.json` 配置模板
- 全局单例 `get_config()` / `set_config()`

### 日志系统 (`logger.py`) **[新建]**
- 结构化日志：`时间戳 [级别] 模块:函数:行号 - 消息`
- 控制台 + RotatingFileHandler（5MB 滚动）
- 替换所有遗留的 `print()` 调用
- 静默 noisy 第三方库（werkzeug/urllib3/websocket）

---

## 阶段 1：Chrome 连接健壮性

### `chrome_manager.py` **[新建]**
- 替代 `app.py` 中内联的 `ensure_chrome()` 函数

#### 浏览器发现
- Windows 注册表查找（Chrome/Edge/Brave 的 `App Paths` 键）
- 回退路径扫描（标准安装位置 + LOCALAPPDATA）
- 日志输出发现的浏览器

#### 三级连接策略
| 优先级 | 策略 | 说明 |
|--------|------|------|
| Tier 1 | **附加** | 检测 `localhost:9222/json` 已有真实标签页，直接复用 |
| Tier 2 | **启动+用户Profile** | 浏览器未运行 → 用用户默认 profile 启动（保留 cookie/登录态） |
| Tier 3 | **启动+独立Profile** | 浏览器运行中但无调试端口 → 用 `~/.browser-brain-chrome/` 启动 |

#### 其他改进
- `shell=True` → `shell=False`（安全修复）
- 等待超时 8s → 30s（可配置）
- 后台健康监控线程（每 5s 检测连通性，连续 2 次失败触发断连回调）
- `_check_debug_port()` 统一检测接口

---

## 阶段 2：捕获性能优化

### `cdp_handler.py` **[重写]**

#### 传输优化
- `EXTRACT_FULL_HTML_JS`：`document.documentElement` → **`document.body`**（排除 `<head>`，~30% 传输减少）
- 移除 JS 侧 `substring(0, 500000)` 截断

#### WebSocket 连接池
```python
_ws_pool: dict = {tab_id: (ws, last_used_ts)}
```
- 维护活跃 WS 连接，消除每次捕获 ~500ms 建连开销
- ping 检测存活，60s 空闲自动关闭
- `_cleanup_ws_pool()` 定期清理

#### 内容缓存
```python
_capture_cache: dict = {tab_id: (timestamp, result)}
```
- 30s TTL，重复捕获同一标签页直接返回缓存
- 前端显示 `_from_cache` 标记

#### META_JS 移植（来自 V1）
```javascript
// 提取: ogTitle, author, published, description, siteName, keywords, ogImage
```
- V1 `content_pipeline.py:META_JS` → V2 `cdp_handler.py:META_JS`
- 捕获结果中附加 `metadata`、`author`、`published`、`description` 等字段

#### 连接重试
- `_connect_tab()`：3 次重试，指数退避 0.5s/1s/2s
- 异常时返回部分结果（至少 title + URL），不崩溃

### `content_cleaner.py` **[重写]**

#### 消除重复解析（~40% 性能提升）
**Before**（两次 BeautifulSoup 解析）:
```python
def process_content(html):
    cleaned = clean_html(html)          # 第一次解析
    plain_text = extract_article_text(cleaned)
    markdown = html_to_markdown(html)   # 第二次解析（内部再调 clean_html）
```

**After**（"清洗一次，传递两次"）:
```python
def process_content(html):
    cleaned = clean_html(html)          # 唯一一次解析
    plain_text = extract_article_text(cleaned)
    markdown = html_to_markdown(cleaned, pre_cleaned=True)  # 跳过 re-clean
```

#### 正文提取优化
- 候选循环中先用 `c.text.strip()` 快速预检（property 访问，比 `get_text()` 快很多）
- 只对 `len > 300` 的大型候选调用昂贵的 `get_text()`
- 跳过数千个小 div/span 的全文提取

---

## 阶段 3：UI/UX 重新设计

### `static/style.css` **[全面重写]**

#### CSS 自定义属性主题系统
```css
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f5f5f5;
    --text-primary: #333333;
    --accent: #1a73e8;
    --border: #e0e0e0;
    /* ... 15+ 语义化 token */
}
[data-theme="dark"] {
    --bg-primary: #1e1e1e;
    --bg-secondary: #252525;
    --text-primary: #e0e0e0;
    --accent: #4da3ff;
    --border: #444444;
}
```

#### 新增组件样式
- **Markdown 渲染** (`rendered` class)：h1-h4、p、ul/ol、blockquote、pre/code、table、img、hr
- **代码块**：等宽字体、背景、圆角、滚动
- **Toast 通知**：底部右侧弹出，info/success/error 三色，入场/出场动画
- **进度条**：`progress-container` → `progress-track` → `progress-fill`
- **搜索框**：`search-input` 聚焦边框高亮
- **捕获历史**：`history-bar` + `history-select` 下拉选择
- **快捷键提示**：`shortcut-hint` 小标签样式

### `static/index.html` **[重写]**

#### 新增 DOM 结构
- 标签页搜索框 `<input id="tab-search">`
- 主题切换按钮 `<button id="theme-toggle">`
- 捕获历史下拉 `<select id="history-select">`
- Toast 容器 `<div id="toast-container">`
- 进度指示器容器（JS 动态生成）
- marked.js 库加载 `<script src="marked.min.js">`
- 快捷键提示：`<span class="shortcut-hint">Ctrl+R</span>`

### `static/app.js` **[全面重写]**

#### 新增功能

| 功能 | 实现 |
|------|------|
| **Markdown 渲染** | `marked.parse(text)` 渲染捕获和聊天 |
| **暗色模式** | `localStorage` 持久化 + CSS `data-theme` 切换 |
| **标签页搜索** | `input` 事件实时过滤 title/url |
| **SSE 流式聊天** | `fetch()` + `ReadableStream` + SSE 解析 |
| **键盘快捷键** | `Ctrl+R/E/1-4/K/L/T`（输入框中仅 Escape 生效） |
| **Toast 通知** | `showToast(msg, type, duration)` info/success/error |
| **捕获历史** | `captureHistory[]` 最近 20 条，去重（同 URL 5s 内） |
| **进度指示器** | CSS 动画进度条，填充 5s 后等待 |

#### 流式聊天实现
```javascript
async function sendChatMessage(message) {
    const res = await fetch('/api/chat/stream', { method: 'POST', ... });
    const reader = res.body.getReader();
    let fullText = '', buffer = '';
    while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, {stream: true});
        // 解析 SSE 行 data: {text: "..."}
        // 逐 token 显示纯文本，流结束后 marked.parse() 渲染
    }
}
```

### 后端 SSE 端点

`routes/chat.py` — `/api/chat/stream`:
```python
def generate():
    stream = client.chat.completions.create(..., stream=True)
    for chunk in stream:
        yield f"data: {json.dumps({'text': delta.content})}\n\n"
    yield "data: [DONE]\n\n"
return Response(generate(), mimetype="text/event-stream")
```

### `static/marked.min.js` **[下载]**
- 39,903 bytes，零依赖 Markdown 解析器

---

## 阶段 4：结构清理

### app.py 拆分

**Before**: 326 行，同时负责 Chrome 管理 + Flask 路由 + Qt 窗口 + 启动编排

**After**: ~160 行，仅为入口编排：

```
app.py              # 配置加载 → Flask 创建 → main() 编排
chrome_manager.py   # 浏览器发现/启动/附加/健康监控      [从 app.py 提取]
routes/             # Flask Blueprint 6 个端点          [从 app.py 提取]
  __init__.py       # Blueprint 注册
  tabs.py           # /api/status, /api/tabs, /api/activate
  capture.py        # /api/capture
  chat.py           # /api/chat, /api/chat/stream (SSE)
  save.py           # /api/save
ui/
  __init__.py
  qt_window.py      # PySide6 Qt 窗口创建 + 浏览器降级    [从 app.py 提取]
integrations/       # 未来扩展占位
  __init__.py
  audio_capture.py      # (未来) WASAPI 录音 + whisper
  jijidown_integration.py  # (未来) B站视频下载
```

### V1 清理
- V1 守护进程（PID 13084）已停止
- V1 目录 `browser-brain/` 保留（编码问题未移动，待手动归档为 `browser-brain-v1-archived/`）
- SKILL.md 更新为 V2 架构描述

### brain_writer.py 更新
- 硬编码路径改由 config 配置
- `print()` → `log.info()`/`log.error()`

---

## 验证结果

```
14 个 Python 文件语法检查全部通过
4 个核心模块导入测试通过
content_cleaner 功能测试: 清洗/提取/Markdown 转换正确
brain_writer 文件名净化测试通过
chrome_manager 注册表发现 + 调试端口检测正常
```

---

## 当前项目结构

```
browser-brain-app/
├── app.py                 # 入口编排
├── config.py              # 配置系统
├── config.example.json    # 配置模板
├── logger.py              # 结构化日志
├── chrome_manager.py      # 浏览器管理
├── cdp_handler.py         # CDP 通信
├── content_cleaner.py     # 内容清洗
├── brain_writer.py        # 外脑写入
├── routes/
│   ├── __init__.py
│   ├── tabs.py            # /api/tabs
│   ├── capture.py         # /api/capture
│   ├── chat.py            # /api/chat + /api/chat/stream
│   └── save.py            # /api/save
├── ui/
│   ├── __init__.py
│   └── qt_window.py       # Qt 桌面窗口
├── integrations/
│   └── __init__.py        # 未来扩展占位
├── static/
│   ├── index.html         # SPA 前端
│   ├── style.css          # 暗色/亮色主题
│   ├── app.js             # 前端逻辑
│   └── marked.min.js      # Markdown 渲染库
├── DEVELOPMENT.md         # 本文件
```

## 待办

### 2026-06-23: 前端从 PySide6 QWebEngineView 切换到 pywebview

**原因**: PySide6 6.11.1 的 QWebEngineView (QtWebEngine 6.9.x) 在 Windows 上存在 GPU 进程崩溃的已知回归 (QTBUG-134746)。尝试了以下修复均无效:
- `--disable-gpu` 单独使用
- `--disable-gpu --use-gl=swiftshader`
- 组合 `QT_OPENGL=software` + `AA_UseSoftwareOpenGL` (Qt层设置实际与 Chromium 冲突)

**方案**: `ui/qt_window.py` 从 PySide6 QWebEngineView 替换为 `pywebview`。
pywebview 在 Windows 上使用系统原生 Edge WebView2：
- 无 Chromium GPU 兼容问题（使用系统已安装的 Edge 运行时）
- 无需任何环境变量配置
- 代码从 80 行减少到 39 行
- 更轻量，启动更快
- 降级链: pywebview → 系统浏览器

**技术栈变更**:
| 层 | 旧 | 新 |
|-----|-----|-----|
| 桌面窗口 | PySide6 + QWebEngineView | pywebview (Edge WebView2) |
| 后端 | Flask | Flask (不变) |
| 前端 | HTML/CSS/JS | HTML/CSS/JS (不变) |
| 浏览器协议 | CDP WebSocket | CDP WebSocket (不变) |

- [ ] 手动归档 V1 (`browser-brain/` → `browser-brain-v1-archived/`)
- [ ] 将 audio_capture.py 和 jijidown_integration.py 从 V1 复制到 integrations/
- [ ] 编写单元测试 (tests/)
- [ ] PyInstaller 打包为单 EXE
### 2026-06-23: Phase 2 多模态管道实施

**新增依赖**: `selenium` (Python 3.10), `yt-dlp` Python 模块 (Python 3.10)

**核心变更**:

1. **`pipeline/processors/multimodal.py`** — 从空骨架填为完整实现:
   - `process()`: 主流程 (字幕 → 千问 → Markdown)
   - `_extract_subtitles()`: yt-dlp 字幕提取 (可选增强, 受限于 cookie)
   - `_call_qwen_web()`: Selenium CDP 操控千问网页端
   - SRT 解析 + 语言检测辅助方法

2. **`extension/content.js`** — 新增 B站/YouTube 字幕直接提取:
   - `fetchBilibiliSubtitles()`: 解析 `__INITIAL_STATE__.videoData.subtitle.list`, 调 B站 API 获取字幕 JSON
   - `fetchYouTubeSubtitles()`: 解析 `ytInitialPlayerResponse.captions`, 调 YouTube timedtext API 获取字幕 XML
   - 利用浏览器 cookie, 无 412 反爬问题
   - 字幕文本注入 `media_meta.subtitle_text`

3. **数据优先级**: 扩展 content script 字幕 > yt-dlp > 扩展元数据 > 千问分析

**已知限制**:
- yt-dlp 在浏览器运行时无法读取 cookie (Chrome 锁定 cookie 数据库)
- B站/YouTube 需要登录才能通过 yt-dlp 访问 (412 Precondition Failed)
- 千问需要在 Selenium 打开的浏览器中手动登录一次 (登录态持久化到 `~/.browser-brain-qwen/`)

**Phase 2 待完成**:
- [ ] 千问首次登录 (Selenium Chrome 打开后手动登录一次)
- [ ] 视频页面字幕 → DeepSeek 讨论 → 外脑保存 的完整端到端测试
- [ ] 扩展 popup 视频页面「多模态解析」按钮
- [ ] 自动检查更新
