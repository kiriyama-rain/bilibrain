# BiliBrain — B站视频内容捕获与知识沉淀

一键捕获 B站视频的字幕、元数据、 AI 辅助分析讨论，自动保存到本地外脑知识库。

> Bilibili video content capture & knowledge tool. Grab subtitles, discuss with AI, save to your personal wiki.

## 开发情况

这个项目最初是我自己用来抓取 B站视频字幕、和 AI 讨论后保存到 Obsidian 知识库的小工具。一开始并没有考虑代码架构，很多功能是"能用就行"——需要字幕就接入 B站 API，需要 OCR 就挂上 PaddleOCR，需要转写就借用另一个项目里的 faster-whisper 模型。插件也没正经打包，一直是以解压模式加载。

**本项目全部代码由 AI（Claude Code）生成**，作者本人不懂编程，是个纯粹的"小白"。如果你发现代码里有奇怪的设计、不规范的写法、或者可以大幅优化的地方——那太正常了，请毫不犹豫地提 Issue 或 PR。

非常欢迎有经验的开发者来完善功能、优化架构、修复 bug。不管是代码重构、测试补充、文档改进还是新功能开发，任何贡献都感激不尽。

## 功能特性

- **B站字幕捕获** — 自动获取 B站视频的 AI 字幕 / CC 字幕（WBI 签名 API + Cookie 认证）
- **硬字幕 OCR** — 无软字幕的视频，通过 PaddleOCR 从画面中直接识别字幕文字
- **语音转文字** — 下载 B站 DASH 音频流，faster-whisper 离线转写
- **AI 讨论** — 通过 DeepSeek API 对视频内容进行结构化分析和讨论（SSE 流式输出）
- **外脑知识库** — 自动保存为 Markdown 文件（YAML front matter），存入本地 Wiki 知识库
- **本地优先** — 所有处理在本地完成，仅 AI 聊天调用外部 API
- **持久化存储** — SQLite 保存捕获和转写历史，服务重启不丢失

## 架构

```
Chrome Extension (MV3)  →  Flask Backend  →  Web UI (SPA)
        ↓                      ↓
   B站字幕/WBI API         DeepSeek API (AI 聊天)
   Cookie 认证                    ↓
                         本地外脑知识库 (Markdown + Wiki)
```

```
browser-brain-app/
├── app.py                    # Flask 入口
├── config.py                 # 配置系统
├── audio_transcriber.py      # faster-whisper 封装
├── hardsub_extractor.py      # PaddleOCR 硬字幕提取
├── brain_writer.py           # 知识库写入
├── capture_store.py          # SQLite 持久化
├── pipeline/                 # 内容处理管道
│   └── processors/
│       ├── webpage.py        # 网页处理器
│       └── multimodal.py     # 多模态处理器
├── routes/                   # API 路由
│   ├── tabs.py               # 标签页查询
│   ├── capture.py            # 内容捕获
│   ├── chat.py               # AI 聊天 (SSE)
│   ├── save.py               # 保存到知识库
│   └── transcribe.py         # 转写 (SSE 进度)
├── static/                   # Web UI (SPA)
│   ├── index.html
│   ├── app.js
│   └── style.css
└── extension/                # Chrome 扩展 (MV3)
    ├── manifest.json
    ├── background.js          # WBI 签名 / 消息路由
    ├── content.js             # DOM 提取 / 字幕 API
    └── popup/                 # 弹出窗口
```

## 快速开始

### 前置要求

- Python 3.10+
- Chrome / Edge / Brave 浏览器
- DeepSeek API key（[获取地址](https://platform.deepseek.com/api_keys)）
- FFmpeg（可选，视频硬字幕提取需要）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/bilibrain.git
cd bilibrain

# 2. 安装依赖
pip install -r requirements.txt

# 3. 复制配置文件
cp config.example.json config.json

# 4. 设置 API Key
# Windows:
set ANTHROPIC_AUTH_TOKEN=sk-your-deepseek-key
# macOS / Linux:
export ANTHROPIC_AUTH_TOKEN=sk-your-deepseek-key

# 5. 启动后端
python app.py
```

### 加载扩展

1. 打开 Chrome，进入 `chrome://extensions/`
2. 开启右上角「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择项目的 `extension/` 目录
5. 扩展图标出现在工具栏，点击或按 `Ctrl+Shift+K` 打开

### 使用流程

1. **打开 B站视频** — 在 Chrome 中正常浏览 B站，确保已登录账号
2. **捕获视频** — 点击扩展图标，选择 B站视频标签页，点击捕获按钮（▶）
3. **AI 讨论** — 在 Web UI（`http://127.0.0.1:5577`）的「聊天」页对视频字幕内容进行 AI 分析
4. **保存外脑** — 在「保存」页将字幕和分析结果写入本地外脑知识库（双层索引）
5. **转写硬字幕** — 如果视频无 AI 字幕，在「转写」页上传视频文件进行 OCR 提取或语音转文字

### 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+K` | 打开扩展弹出窗口 |
| `Ctrl+1` | 捕获页 |
| `Ctrl+2` | 聊天页 |
| `Ctrl+3` | 保存页 |
| `Ctrl+4` | 转写页 |
| `Ctrl+5` | 历史页 |

## 配置

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|:--:|--------|------|
| `ANTHROPIC_AUTH_TOKEN` | 是 | — | DeepSeek API key |
| `ANTHROPIC_BASE_URL` | 否 | `https://api.deepseek.com` | API 端点（兼容 OpenAI 接口） |
| `ANTHROPIC_MODEL` | 否 | `deepseek-v4-flash` | 模型名称 |

### config.json

复制 `config.example.json` 为 `config.json` 后修改。主要配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `flask_port` | `5577` | Web UI 端口 |
| `outbrain_dir` | `~/外脑` | 知识库存储目录 |
| `raw_clippings_subdir` | `raw/视频与博客` | 剪藏子目录 |
| `ffmpeg_path` | 自动检测 | FFmpeg 路径 |
| `whisper_model_dir` | `~/.browser-brain/whisper-models` | Whisper 模型缓存 |
| `sqlite_db_path` | `~/.browser-brain/captures.db` | 数据库路径 |

配置加载优先级：`./config.json` > `~/.browser-brain/config.json` > 环境变量 > 默认值

## 可选功能

### 视频硬字幕提取 (PaddleOCR)

适用于画面中烧录了字幕但无软字幕文件的视频。

```bash
pip install paddleocr pillow
```

FFmpeg 需在 PATH 中，或通过 `config.json` 的 `ffmpeg_path` 指定。

### 音频转文字 (faster-whisper)

```bash
pip install faster-whisper
```

模型在首次使用时自动下载到 `whisper_model_dir`（默认 `~/.browser-brain/whisper-models`）。

| 模型 | 大小 | 速度 | 精度 |
|------|------|------|------|
| tiny | ~150MB | 极快 | 一般 |
| base | ~290MB | 快 | 尚可 |
| small | ~490MB | 中等 | 较好 |
| medium | ~1.5GB | 较慢 | 很好 |
| large-v3 | ~3GB | 慢 | 最佳 |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 健康检查 |
| `/api/tabs` | GET | 列出浏览器标签页 |
| `/api/capture` | POST | 捕获页面内容 |
| `/api/captures` | GET | 列出捕获历史 |
| `/api/captures/<id>` | GET | 获取捕获详情 |
| `/api/chat` | POST | AI 聊天（非流式） |
| `/api/chat/stream` | POST | AI 聊天（SSE 流式） |
| `/api/save` | POST | 保存到知识库 |
| `/api/transcribe` | POST | 上传文件转写（SSE 进度） |
| `/api/transcriptions` | GET | 列出转写历史 |
| `/api/shutdown` | POST | 关闭 Flask 服务 |

## B站 字幕提取

扩展通过 WBI 签名 API (`/x/player/wbi/v2`) 获取字幕和 DASH 音频流。需要登录 B站 账号（在 Chrome 中正常登录即可，扩展自动读取 cookie）。

**技术要点：**
- MV3 service worker 不自动发送 SameSite=Lax cookie
- 通过 `chrome.cookies.getAll({domain: '.bilibili.com'})` 手动构建 Cookie header
- 关键认证 cookie: `SESSDATA`, `bili_jct`, `DedeUserID`
- 纯 JS 实现 MD5 + WBI 混合密钥签名

## 技术实现

以下是每个功能模块的实现方式、依赖和借鉴的技术。

### 网页内容捕获

```
Chrome Extension content script → DOM 提取 → Flask 后端 → Markdown 转换
```

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 页面正文提取 | 优先 `<article>` → `<main>` → 最大文本块 → `<body>` 兜底 | 参考 Readability.js 的候选评分思路，简化为取最长文本块 |
| HTML 清洗 | 克隆 body 后移除 script/style/nav/footer/aside 等标签 | 借鉴 Obsidian Web Clipper 的元素过滤策略 |
| 元数据提取 | `<meta>` 标签 + Open Graph 属性（og:title/description/image） | 标准 SEO 元数据规范 |
| Markdown 转换 | 自定义 `content_cleaner.py`，先清洗再一次遍历转 Markdown | 避免两次 BeautifulSoup 解析，性能提升 ~40% |

### B站 字幕提取

```
URL 提取 bvid → view API 获取 cid → WBI 签名 player API → 下载字幕 JSON
```

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| WBI 签名 | 纯 JS 实现 MD5 哈希 + img_key/sub_key 混合密钥 | 参考 B站 社区 WBI 签名算法文档（GitHub: SocialSisterYi/bilibili-API-collect） |
| Cookie 认证 | `chrome.cookies.getAll({domain: '.bilibili.com'})` 手动拼接 Cookie header | MV3 service worker 不自动发送 SameSite 跨站 cookie，需手动读取 |
| 字幕解析 | B站 字幕 JSON `{body: [{from, to, content}]}` → 纯文本行 | B站 API 返回格式 |
| 音频流提取 | 从 DASH 数据中选择最高码率音频流，保存备用 URL | 用于硬字幕视频的 whisper 降级方案 |

**踩坑记录**：B站 API 认证是最大的坑。先后尝试了 6 种方案才成功——content script 直接 fetch（CORS 拦截）、background.js + credentials:'include'（MV3 不自动发 SameSite cookie）、页面注入 `<script>` 标签（CSP `script-src-elem` 阻止）、Blob URL 注入（同 CSP 拦截）、`chrome.scripting.executeScript({world:'MAIN'})`（消息丢失）。最终回到 `chrome.cookies.getAll` 手动 Cookie 头方案，通过诊断日志确认 SESSDATA/bili_jct/DedeUserID 三个关键 cookie 都齐全后才成功。

### 硬字幕提取（PaddleOCR）

```
视频文件 → ffmpeg 每2秒截帧 → 裁剪底部22%区域 → 2x放大 → PaddleOCR识别 → 相邻帧去重
```

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 视频抽帧 | ffmpeg `fps=0.5`（每2秒1帧） | ffmpeg 命令行 |
| 字幕区域裁剪 | PIL 裁剪画面底部 22%（字幕通常在此区域） | 经验值，大多数视频字幕占据底部 15%~25% |
| OCR 引擎 | PaddleOCR 3.x，PP-OCRv5_mobile 模型 | 百度 PaddleOCR 开源项目 |
| 模型选择 | mobile 版而非 server 版 | server 版单帧 15 秒，mobile 版仅 0.4 秒（35x 加速）；字幕文字清晰规则，mobile 精度完全够用 |
| 去重策略 | 相邻帧文字相同则合并，保留首次时间戳 | 视频相邻帧字幕通常不变 |
| 实时进度 | SSE (Server-Sent Events) 推送每帧识别进度 | Flask + threading + queue 实现 |

**性能数据**（18分钟/436MB/1080p 视频）：552 帧 → 456 条字幕 → 11,814 字，4 分钟完成。

### 语音转文字（faster-whisper）

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 模型引擎 | faster-whisper（OpenAI Whisper 的 CTranslate2 重实现） | Systran/faster-whisper |
| 模型管理 | 首次使用时自动从 HuggingFace 下载，缓存到本地目录 | HuggingFace Hub |
| VAD 过滤 | `vad_filter=True`，500ms 静音分段 | 语音活动检测，减少无效片段 |
| 中文优化 | `language="zh"` + `beam_size=5` | beam search 提升中文识别精度 |

### AI 聊天（DeepSeek API）

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| API 调用 | OpenAI Python SDK（兼容接口） | DeepSeek API 兼容 OpenAI 格式 |
| 流式输出 | SSE (Server-Sent Events)，逐 token 推送到前端 | Flask `Response` + generator |
| 系统提示词 | 结构化角色定义 + 核心原则 + 输出规范 + 行为约束 | 借鉴 Anthropic 的 system prompt 工程实践 |
| 上下文注入 | 将捕获内容嵌入提示词的 `{context}` 占位符（截断至 8000 字） | RAG 思路的简化版 |

### 外脑知识库

外脑（Outbrain）是一个基于 **LLM Wiki 模式**（借鉴 Karpathy 的 LLM Wiki 设计）构建的个人知识库系统。所有 B站视频捕获内容最终都沉淀到这里。

#### 三层架构

```
外脑/
├── raw/                    # 第1层：原始资料（只读，不修改）
│   └── 视频与博客/           #   浏览器捕获的原内容，保留来源 URL
├── wiki/                   # 第2层：AI 维护的知识库
│   ├── 摘要/                #   视频内容的 AI 分析总结
│   ├── 概念/                #   提取的关键概念和术语
│   ├── 主题/                #   按主题组织的知识页面
│   ├── index.md             #   全库目录索引（自动维护）
│   └── log.md               #   变更日志（每次写入追加）
└── SCHEMA.md               # 维护规则手册
```

#### 原文索引与来源追溯

每条知识都保留了完整的来源链：

```
wiki/摘要/某个视频分析.md
  ├── YAML front matter:
  │     source: "raw/视频与博客/视频标题-bilibili.md"   ← 指向原始文件
  │     url: "https://www.bilibili.com/video/BVxxx"     ← 原始 URL
  │     created: 2026-06-24
  │     tags: [摘要, bilibili]
  └── 正文: AI 分析内容 + 原文引用
```

这保证了：
- **来源可查**：任何分析结论都能追溯到原始视频和字幕
- **双向链接**：wiki 页面通过 `[[wiki/概念/xxx]]` 互相引用，形成知识网络
- **索引自动更新**：每次保存自动更新 `wiki/index.md` 目录
- **变更可审计**：每次写入追加到 `wiki/log.md`

#### 写入流程

```
捕获 B站视频
  → 1. 写入 raw/视频与博客/（标题+字幕+元数据，YAML front matter）
  → 2. 可选：AI 分析后写入 wiki/摘要/（分析文章，标注 source 指向 raw）
  → 3. 自动更新 wiki/index.md（新增目录条目）
  → 4. 追加 wiki/log.md（记录变更）
```

### 数据持久化

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 数据库 | SQLite，WAL 模式支持并发读取 | Python 标准库 `sqlite3` |
| 表结构 | `captures` 表（id/url/title/markdown/metadata）+ `transcriptions` 表 | 简单 CRUD，无需 ORM |

### 前端 UI

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 架构 | 纯 HTML/CSS/JS SPA，5 个标签页 | 无框架，零构建步骤 |
| Markdown 渲染 | marked.js（39KB，零依赖） | 轻量级选择 |
| 暗色模式 | CSS 自定义属性 + `localStorage` 持久化 | 系统主题跟随 |
| 流式聊天 | `fetch()` + `ReadableStream` + SSE 行解析 | 标准 Web API |
| 设计风格 | 简洁卡片式，蓝白配色 | 参考 Google Material Design 简约风格 |

### Chrome Extension

| 环节 | 实现 | 依赖/借鉴 |
|------|------|-----------|
| 版本 | Manifest V3 | Chrome 最新扩展规范 |
| 消息通信 | `chrome.runtime.sendMessage` 路由 | MV3 标准 API |
| 背景服务 | Service Worker（非持久化） | 替代 MV2 的 persistent background page |
| 内容注入 | `content.js` 注入所有页面（`<all_urls>`） | document_idle 时机注入 |


## 开发

详见 [DEVELOPMENT.md](DEVELOPMENT.md) 了解架构决策和优化历史。
详见 [PHASE2_RESEARCH.md](PHASE2_RESEARCH.md) 了解多模态管道技术调研。

## License

MIT — 详见 [LICENSE](LICENSE)
