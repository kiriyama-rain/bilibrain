"""
Chrome 管理器 — 浏览器发现 / 启动 / 附加 / 健康监控
=================================================
三级连接策略:
  1. 附加: 检测已有调试端口 → 直接复用用户运行的浏览器
  2. 启动+用户Profile: 浏览器未运行时，以用户默认 profile 启动
  3. 启动+独立Profile: 最后手段，新建独立 profile
"""
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from logger import get_logger

log = get_logger(__name__)

# ─── 浏览器发现 ────────────────────────────────────────────────


def _find_browser_in_registry(reg_path: str) -> Optional[str]:
    """从 Windows 注册表查找浏览器路径"""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
            path, _ = winreg.QueryValueEx(key, "")
            if Path(path).exists():
                return path
    except OSError:
        pass
    return None


def find_installed_browsers(registry_keys: dict, fallback_paths: dict) -> dict:
    """
    发现所有已安装的浏览器。
    返回 {browser_name: executable_path}
    """
    found = {}

    # 1. 注册表查找
    for name, reg_path in registry_keys.items():
        path = _find_browser_in_registry(reg_path)
        if path:
            found[name] = path
            log.debug(f"注册表发现 {name}: {path}")

    # 2. 回退路径扫描
    for name, paths in fallback_paths.items():
        if name not in found:
            for p in paths:
                expanded = os.path.expandvars(p)
                if Path(expanded).exists():
                    found[name] = expanded
                    log.debug(f"路径扫描发现 {name}: {expanded}")
                    break

    return found


# ─── Chrome 启动与附加 ─────────────────────────────────────────


def _check_debug_port(port: int, timeout: float = 2.0) -> Tuple[bool, list]:
    """
    检查调试端口是否有真实标签页。
    返回 (has_real_tabs, tabs_list)
    """
    try:
        req = urllib.request.urlopen(
            f"http://localhost:{port}/json", timeout=timeout
        )
        tabs = json.loads(req.read())
        real = [
            t
            for t in tabs
            if not t.get("url", "").startswith("chrome://")
            and not t.get("url", "").startswith("devtools://")
            and t.get("url", "") not in ("", "about:blank")
        ]
        return len(real) > 0, real
    except Exception:
        return False, []


def wait_for_chrome(port: int, timeout: float, poll_interval: float = 1.0) -> Tuple[bool, str]:
    """
    轮询等待 Chrome 调试端口就绪。
    返回 (success, message)
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, tabs = _check_debug_port(port, timeout=2.0)
        if ok:
            return True, f"已连接 ({len(tabs)} 个标签页)"
        time.sleep(poll_interval)

    return False, f"启动超时 ({timeout:.0f}秒)"


def _get_user_data_dir(browser_name: str, templates: dict) -> Optional[str]:
    """获取浏览器默认用户数据目录"""
    template = templates.get(browser_name, "")
    if not template:
        return None
    localappdata = os.environ.get("LOCALAPPDATA", "")
    path = template.format(localappdata=localappdata)
    return path if Path(path).exists() else None


def _is_browser_running(browser_path: str) -> bool:
    """检查浏览器进程是否已在运行"""
    name = Path(browser_path).name.lower()
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True,
        )
        return name in result.stdout.lower()
    except Exception:
        return False


def launch_chrome(
    browser_path: str,
    port: int,
    user_data_dir: str = None,
    reuse_existing: bool = False,
) -> Optional[subprocess.Popen]:
    """
    启动浏览器调试模式。
    - user_data_dir: None = 不指定（使用默认），传路径则指定
    - reuse_existing: True = 如果浏览器已运行则不启动
    """
    if reuse_existing and _is_browser_running(browser_path):
        log.info("浏览器已在运行，跳过启动")
        return None

    args = [
        browser_path,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    if user_data_dir:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={user_data_dir}")

    try:
        proc = subprocess.Popen(
            args,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"启动浏览器: {browser_path} (PID {proc.pid})")
        return proc
    except Exception as e:
        log.error(f"浏览器启动失败: {e}")
        return None


def attach_or_launch(
    port: int = 9222,
    timeout: float = 30.0,
    poll_interval: float = 1.0,
    registry_keys: dict = None,
    fallback_paths: dict = None,
    user_data_templates: dict = None,
    isolated_profile_dir: str = "",
    attach_only: bool = False,
) -> Tuple[bool, str, Optional[subprocess.Popen], Optional[str]]:
    """
    三级连接策略。返回 (ok, msg, process, browser_name)

    1. 附加: 调试端口已有标签页 → 直接使用
    2. 启动+用户Profile: 浏览器未运行 → 用用户默认 profile 启动
    3. 启动+独立Profile: 浏览器正在运行但无调试端口 → 用独立 profile 启动
    """
    # ── Tier 1: 附加到已有调试端口 ─────────────────
    ok, tabs = _check_debug_port(port, timeout=2.0)
    if ok:
        return True, f"附加成功 ({len(tabs)} 个标签页)", None, None

    if attach_only:
        return False, "Chrome 调试端口未开启且 attach_only=true", None, None

    # ── 发现浏览器 ─────────────────────────────────
    registry_keys = registry_keys or {}
    fallback_paths = fallback_paths or {}
    user_data_templates = user_data_templates or {}

    browsers = find_installed_browsers(registry_keys, fallback_paths)
    if not browsers:
        return False, "未找到已安装的浏览器 (Chrome/Edge/Brave)", None, None

    # 优先 Chrome，其次 Edge，最后 Brave
    preferred = ["chrome", "edge", "brave"]
    browser_name = None
    browser_path = None
    for name in preferred:
        if name in browsers:
            browser_name = name
            browser_path = browsers[name]
            break

    if not browser_path:
        return False, "找不到可用的浏览器", None, None

    log.info(f"选择浏览器: {browser_name} ({browser_path})")

    # ── Tier 2: 浏览器未运行 → 使用用户 profile ────
    if not _is_browser_running(browser_path):
        user_data = _get_user_data_dir(browser_name, user_data_templates)
        if user_data:
            log.info(f"Tier 2: 使用用户 profile 启动 ({user_data})")
            proc = launch_chrome(browser_path, port, user_data_dir=user_data)
        else:
            log.info("Tier 2: 用户 profile 不可用，使用独立 profile")
            proc = launch_chrome(browser_path, port,
                                 user_data_dir=isolated_profile_dir)
    else:
        # ── Tier 3: 浏览器正在运行但无调试端口 ────────
        log.info("Tier 3: 浏览器已在运行但无调试端口，使用独立 profile")
        proc = launch_chrome(browser_path, port,
                             user_data_dir=isolated_profile_dir)

    if proc is None:
        return False, "浏览器启动失败", None, None

    # 等待就绪
    ok, msg = wait_for_chrome(port, timeout, poll_interval)
    return ok, msg, proc, browser_name


def cleanup_chrome(proc: Optional[subprocess.Popen]):
    """安全终止浏览器进程"""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.info("Chrome 进程已清理")
    except Exception as e:
        log.warning(f"清理 Chrome 进程时出错: {e}")


# ─── 健康监控 ──────────────────────────────────────────────────


def start_health_monitor(
    port: int,
    check_interval: float = 5.0,
    failure_threshold: int = 2,
    on_disconnect: callable = None,
    on_reconnect: callable = None,
) -> threading.Thread:
    """
    后台线程：定期检测 CDP 连通性。
    - check_interval: 检测间隔（秒）
    - failure_threshold: 连续失败次数阈值
    - on_disconnect: 断连回调
    - on_reconnect: 重连回调
    """
    stop_event = threading.Event()
    consecutive_failures = 0
    was_connected = True

    def _monitor():
        nonlocal consecutive_failures, was_connected
        while not stop_event.is_set():
            time.sleep(check_interval)
            ok, _ = _check_debug_port(port, timeout=2.0)

            if ok:
                consecutive_failures = 0
                if not was_connected and on_reconnect:
                    log.info("Chrome 连接已恢复")
                    on_reconnect()
                was_connected = True
            else:
                consecutive_failures += 1
                if consecutive_failures >= failure_threshold and was_connected:
                    log.warning(f"Chrome 连接丢失 (连续 {consecutive_failures} 次)")
                    was_connected = False
                    if on_disconnect:
                        on_disconnect()

    t = threading.Thread(target=_monitor, daemon=True)
    t.stop_event = stop_event
    t.start()
    log.debug("健康监控线程已启动")
    return t
