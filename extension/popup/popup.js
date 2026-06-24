/**
 * Browser Brain — Popup UI
 * =========================
 * 扩展弹出窗口: 标签页列表 + 快捷捕获 + 跳转完整 Web UI
 *
 * Phase 2 预留:
 *   - 内容类型图标 (网页/视频/音频)
 *   - 视频页面的「多模态解析」按钮
 *   - media_meta 数据传递给 capture API
 */
'use strict';

const FLASK_URL = 'http://127.0.0.1:5577';

// ─── 状态 ──────────────────────────────────────────────
let tabs = [];
let activeTabId = null;

// ─── DOM ────────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const dom = {
  statusDot: $('#status-dot'),
  tabList: $('#tab-list'),
  btnRefresh: $('#btn-refresh'),
  btnOpenFull: $('#btn-open-full'),
  btnCaptureActive: $('#btn-capture-active'),
  captureStatus: $('#capture-status'),
};

// ─── 初始化 ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await checkFlaskHealth();
  await loadTabs();
  setInterval(checkFlaskHealth, 10000);
});

// ─── Flask 健康检查 ────────────────────────────────────
async function checkFlaskHealth() {
  try {
    const resp = await fetch(`${FLASK_URL}/api/status`);
    if (resp.ok) {
      dom.statusDot.className = 'dot online';
      dom.statusDot.title = '后端在线';
    } else {
      throw new Error('unhealthy');
    }
  } catch (e) {
    dom.statusDot.className = 'dot offline';
    dom.statusDot.title = '后端离线 — 请启动 python app.py';
  }
}

// ─── 加载标签页 ────────────────────────────────────────
async function loadTabs() {
  dom.tabList.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const resp = await chrome.runtime.sendMessage({ action: 'getTabs' });
    tabs = resp.tabs || [];
    if (!tabs.length) {
      dom.tabList.innerHTML = '<div class="empty">没有可用的标签页</div>';
      return;
    }
    renderTabs();
  } catch (e) {
    dom.tabList.innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

function renderTabs() {
  dom.tabList.innerHTML = '';
  tabs.forEach(tab => {
    const el = document.createElement('div');
    el.className = 'tab-item' + (tab.active ? ' active' : '');

    const typeIcon = getTypeIcon(tab.url);  // Phase 2: 内容类型图标

    el.innerHTML = `
      <img class="favicon" src="${tab.favicon || ''}">
      <div class="tab-info">
        <div class="tab-title">
          <span class="type-icon">${typeIcon}</span>
          ${escapeHtml(tab.title || '无标题')}
        </div>
        <div class="tab-url">${escapeHtml(tab.url || '')}</div>
      </div>
      <button class="btn-capture" data-id="${tab.id}" title="捕获此页面">▶</button>
    `;

    // 程序化绑定 onerror, 避免 CSP 拦截
    const faviconImg = el.querySelector('.favicon');
    faviconImg.onerror = function() { this.style.display = 'none'; };

    el.querySelector('.btn-capture').addEventListener('click', (e) => {
      e.stopPropagation();
      captureTab(tab.id, tab);
    });

    el.addEventListener('click', () => {
      chrome.runtime.sendMessage({ action: 'activateTab', tabId: tab.id });
    });

    dom.tabList.appendChild(el);
  });
}

// ─── 内容类型图标 (Phase 2 预留) ───────────────────────

function getTypeIcon(url) {
  const host = (url || '').toLowerCase();
  const videoDomains = ['youtube.com', 'youtu.be', 'bilibili.com', 'douyin.com', 'tiktok.com', 'iqiyi.com', 'youku.com', 'v.qq.com', 'twitch.tv'];
  const audioDomains = ['music.163.com', 'y.qq.com', 'spotify.com', 'soundcloud.com'];

  for (const d of videoDomains) {
    if (host.includes(d)) return '🎬';
  }
  for (const d of audioDomains) {
    if (host.includes(d)) return '🎵';
  }
  return '📄';
}

// ─── 捕获标签页 ────────────────────────────────────────
async function captureTab(tabId, tabInfo) {
  dom.captureStatus.textContent = '提取中...';
  dom.captureStatus.className = 'capture-status loading';
  console.log('[BB] Step1: sendMessage extractContent to tab', tabId);

  try {
    // 1. 从 content script 提取页面内容
    const extractResp = await chrome.runtime.sendMessage({
      action: 'extractContent',
      tabId: tabId,
    });
    console.log('[BB] Step2: extractContent response', Object.keys(extractResp || {}));

    if (extractResp.error) {
      console.error('[BB] Step2 FAILED:', extractResp.error);
      throw new Error('提取: ' + extractResp.error);
    }
    if (chrome.runtime.lastError) {
      console.error('[BB] Step2 lastError:', chrome.runtime.lastError.message);
      throw new Error('提取: ' + chrome.runtime.lastError.message);
    }

    const content = extractResp;
    console.log('[BB] Step3: got content. title=', (content.title||'').substring(0,40),
                'url=', (content.url||'').substring(0,40),
                'html_len=', (content.body_html||'').length,
                'text_len=', content.text_length,
                'type=', content.content_type);

    // 2. 发送到 Flask 后端处理
    console.log('[BB] Step4: callFlask /api/capture');
    const flaskResp = await chrome.runtime.sendMessage({
      action: 'callFlask',
      endpoint: '/api/capture',
      data: {
        url: content.url,
        title: content.title,
        body_html: content.body_html,
        body_text: content.body_text,
        metadata: content.metadata,
        content_type: content.content_type,    // Phase 2
        media_meta: content.media_meta,        // Phase 2
        captured_via: 'extension',
      },
    });
    console.log('[BB] Step5: Flask response', {success: flaskResp.success, error: flaskResp.error});

    if (flaskResp.success) {
      console.log('[BB] Step6: SUCCESS!');
      dom.captureStatus.textContent = '已捕获！';
      dom.captureStatus.className = 'capture-status success';
      // 捕获完成，结果已保存到 Flask 后端
      // 点击「⤢」按钮可打开 Web UI 进行 AI 讨论和保存到外脑
    } else {
      console.error('[BB] Step5 FAILED:', flaskResp.error);
      throw new Error('Flask: ' + flaskResp.error);
    }
  } catch (e) {
    console.error('[BB] FATAL:', e.message, e.stack);
    dom.captureStatus.textContent = `失败: ${e.message}`;
    dom.captureStatus.className = 'capture-status error';
  }
}

// ─── 按钮事件 ──────────────────────────────────────────
dom.btnRefresh.addEventListener('click', loadTabs);

dom.btnOpenFull.addEventListener('click', () => {
  chrome.tabs.create({ url: FLASK_URL });
});

dom.btnCaptureActive.addEventListener('click', () => {
  const active = tabs.find(t => t.active);
  if (active) {
    captureTab(active.id, active);
  } else {
    dom.captureStatus.textContent = '没有活跃标签页';
    dom.captureStatus.className = 'capture-status error';
  }
});

// ─── 工具函数 ──────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
