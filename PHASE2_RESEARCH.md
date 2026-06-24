# Browser Brain — Phase 2 多模态管道技术调研

> 2026-06-23 | 调研完成，待实施

## 核心发现

两个关键发现推翻了原方案：

### 发现 1: 根本不需要下载视频文件

`yt-dlp --write-subs --skip-download <url>` 直接提取字幕，零字节视频下载。YouTube、B站等 30+ 平台都支持内建字幕。

### 发现 2: 不需要千问 API Key

通过 Selenium + Chrome DevTools Protocol 自动化操控千问网页端（chat.qwen.ai），拦截 Network 请求获取原始响应。已有开源实现 [qwen_bot](https://github.com/rodolflying/qwen_bot)。

---

## 技术点 1: yt-dlp 字幕提取

### 当前环境
- yt-dlp 版本: **2026.03.17** (已安装)
- Selenium: **未安装** (需 `pip install selenium`)

### 核心命令

```bash
# 列出视频可用字幕
yt-dlp --list-subs "URL"

# 只提取字幕/元数据，完全不下载视频
yt-dlp --write-subs --write-auto-subs --skip-download --sub-format srt "URL"

# 输出 JSON 元数据 (包含字幕 URL、标题、描述、时长等)
yt-dlp --dump-json --skip-download "URL"
```

### Python 集成模式

```python
import yt_dlp

def extract_video_info(url: str) -> dict:
    """提取视频元数据 + 字幕文本，不下载视频"""
    ydl_opts = {
        'skip_download': True,          # 关键: 不下载视频
        'writesubtitles': True,         # 下载手动字幕
        'writeautosub': True,           # 也下载 AI 自动字幕
        'subtitlesformat': 'srt',       # SRT 格式便于解析
        'subtitleslangs': ['zh-Hans', 'en', 'ai-zh', 'ai-en'],
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # info 包含:
        #   title, description, duration, uploader
        #   subtitles: {lang: [{url, ext}]}
        #   automatic_captions: {lang: [{url, ext}]}
        return info
```

### 平台覆盖

| 平台 | 字幕支持 | 备注 |
|------|---------|------|
| YouTube | 手动 + AI 自动字幕 | 语言丰富 |
| Bilibili | 手动 + AI 字幕 | BCC 格式，yt-dlp 自动转 SRT |
| Youku/iQiyi/Tencent | 部分支持 | 需要 cookie 登录 |
| TikTok/Douyin | AI 字幕 | 自动生成 |
| Twitch | 手动字幕 | VOD 支持 |

### B站特殊处理
- B站字幕语言标签: `zh-Hans`(中文), `ai-zh`(AI中文)
- 弹幕可通过 `yt-dlp-danmaku` 插件提取为字幕
- 需要登录时: `--cookies-from-browser chrome`

### SRT 解析 → 纯文本

```python
def parse_srt_to_text(srt_content: str) -> str:
    lines = []
    for line in srt_content.split('\n'):
        line = line.strip()
        if not line or '-->' in line or line.isdigit():
            continue
        # 去掉 HTML 标签和内联时间戳
        text = line.split('<', 1)[0] if '<' in line else line
        if text:
            lines.append(text)
    return '\n'.join(lines)
```

---

## 技术点 2: 千问网页端 Selenium 自动化

### 方案对比

| 方案 | 工具 | 平台 | 难点 |
|------|------|------|------|
| A: Network 拦截 | Selenium CDP | Win/Linux/Mac | **推荐** — 捕获原始 API 响应，不依赖 DOM |
| B: DOM 轮询 | Selenium | Win/Linux/Mac | 脆弱 — UI 改版就坏 |
| C: AppleScript | web_llm_interactor | **Mac only** | 无法在 Windows 使用 |

### 方案 A — Network 拦截 (推荐)

核心原理: Selenium 4.x 内置 Chrome DevTools Protocol 支持，通过性能日志 (`goog:loggingPrefs`) 拦截 `Network.requestWillBeSent` 事件，直接拿到千问后端 API 的请求/响应。

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json, time

class QwenWebChat:
    """通过 Selenium CDP 操控千问网页端"""

    def __init__(self, headless: bool = False):
        options = webdriver.ChromeOptions()
        # 启用性能日志 — 这是 Network 拦截的关键
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        if headless:
            options.add_argument("--headless=new")
        self.driver = webdriver.Chrome(options=options)
        self._logged_in = False

    def login_if_needed(self):
        """手动登录 (仅第一次)"""
        self.driver.get("https://chat.qwen.ai/")
        input("请在浏览器中登录千问，完成后按 Enter...")
        self._logged_in = True

    def send_message(self, prompt: str):
        """向千问发送消息"""
        # 等待输入框就绪
        textarea = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "textarea"))
        )
        textarea.send_keys(prompt)
        # 点击发送按钮
        send_btn = self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        )
        send_btn.click()

    def wait_for_response(self, timeout: int = 60) -> str:
        """等待 AI 回复完成 (检测停止按钮消失)"""
        try:
            WebDriverWait(self.driver, timeout).until_not(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[aria-label='Stop generating']")
                )
            )
        except Exception:
            pass
        time.sleep(1)
        # 提取最后一条 AI 消息
        messages = self.driver.find_elements(
            By.CSS_SELECTOR, "[class*='assistant'], .ai-message"
        )
        return messages[-1].text if messages else ""

    def get_network_response(self) -> dict | None:
        """从性能日志中提取 API 响应 (备选/验证用)"""
        logs = self.driver.get_log("performance")
        for entry in logs:
            log = json.loads(entry["message"])
            msg = log.get("message", {})
            method = msg.get("method", "")
            if method == "Network.responseReceived":
                url = msg.get("params", {}).get("response", {}).get("url", "")
                if "chat" in url or "completion" in url:
                    return msg["params"]["response"]
        return None

    def ask(self, prompt: str) -> str:
        """一键询问"""
        self.send_message(prompt)
        return self.wait_for_response()

    def close(self):
        self.driver.quit()
```

### 关键注意事项

1. **首次使用需要手动登录** — 千问网页端需要账号，Selenium 打开的浏览器可以手动登录一次，之后 cookie 持久化
2. **Chrome 用户数据目录** — 使用 `--user-data-dir` 保持登录态:
   ```python
   options.add_argument(f"--user-data-dir={user_data_dir}")
   ```
3. **反爬检测** — 千问目前对 Selenium 检测不严，如果遇到验证码可能需要 `undetected-chromedriver`
4. **超时处理** — 长视频分析可能超时，建议 120s timeout

---

## 技术点 3: 完整 Pipeline 集成

### 修订后的数据流

```
Extension 捕获视频 URL (B站/YouTube)
        │
        ▼
Flask pipeline/router.py  detect_content_type()
        │
        │ content_type = "video"
        ▼
pipeline/processors/multimodal.py
        │
        ├─ Step 1: yt-dlp 提取字幕 + 元数据
        │     yt-dlp --write-subs --write-auto-subs --skip-download <url>
        │     输出: {title, description, duration, subtitles_text, ...}
        │
        ├─ Step 2: (如无字幕或字幕不足) 千问网页端补充分析
        │     QwenWebChat.ask(f"请描述这个视频的内容: 标题={title}, 描述={desc}")
        │     输出: 千问文字描述
        │
        ├─ Step 3: 整合 → DeepSeek API 讨论/总结
        │     context = f"视频标题: {title}\n字幕: {subs}\n千问分析: {qwen_analysis}"
        │     DeepSeek: "请综合以上信息，做深度讨论和结构化总结"
        │
        └─ Step 4: 保存到外脑
              brain_writer.save_capture()
```

### 需要安装的依赖

```bash
# Python 3.10
pip install selenium          # 浏览器自动化
# yt-dlp 已安装
```

### 文件变更计划

| 文件 | 变更 |
|------|------|
| `pipeline/processors/multimodal.py` | 填入 `_download_media()` → yt-dlp 字幕提取; `_call_qwen()` → Selenium 网页端; 实现完整 `process()` |
| `extension/popup/popup.js` | 视频页面的「多模态解析」按钮 |
| `config.py` | 新增 `qwen_url`, `qwen_headless`, `chrome_user_data_dir` 等配置项 |

### 当前已就绪

| 组件 | 状态 |
|------|------|
| yt-dlp | ✅ 已安装 (2026.03.17) |
| Selenium | ❌ 待安装 |
| Qwen 网页端账号 | 待确认 |
| `pipeline/processors/multimodal.py` 骨架 | ✅ 接口已定义 |
| `pipeline/router.py` 路由 | ✅ 视频 URL 自动检测 |
| `extension/content.js` 视频元数据提取 | ✅ B站/YouTube |
