/**
 * Browser Brain — 前端逻辑 v2
 * =============================
 * 功能:
 *   - marked.js Markdown 渲染
 *   - SSE 流式聊天
 *   - 标签页搜索/过滤
 *   - 键盘快捷键
 *   - Toast 通知
 *   - 捕获历史 (最近 20 条)
 *   - 暗色/亮色主题
 *   - 进度指示器
 */
(function() {
  'use strict';

  // ─── 状态 ──────────────────────────────────────────────
  let state = {
    tabs: [],
    selectedTabId: null,
    currentCapture: null,
    chatHistory: [],
    generatedSummary: '',   // 跨页摘要: 聊天/保存之间传递
  };
  let captureHistory = [];
  const MAX_HISTORY = 20;

  // ─── DOM 引用 ──────────────────────────────────────────
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  const dom = {
    serverStatus: $('#server-status'),
    statusDot: $('#server-status'),
    statusText: $('#status-text'),
    btnShutdown: $('#btn-shutdown'),
    tabList: $('#tab-list'),
    tabSearch: $('#tab-search'),
    captureResult: $('#capture-result'),
    captureActions: $('#capture-actions'),
    captureSource: $('#capture-source'),
    historyBar: $('#history-bar'),
    historySelect: $('#history-select'),
    chatMessages: $('#chat-messages'),
    chatInput: $('#chat-input'),
    saveForm: $('#save-form'),
    btnCapture: $('#btn-capture'),
    btnSummary: $('#btn-summary'),
    btnChatAbout: $('#btn-chat-about'),
    btnSaveCapture: $('#btn-save-capture'),
    btnSend: $('#btn-send'),
    btnClearChat: $('#btn-clear-chat'),
    btnRefreshTabs: $('#refresh-tabs'),
    chatContext: $('#chat-context'),
    chatContextBar: $('#chat-context-bar'),
    contextBarTitle: $('#context-bar-title'),
    contextBarUrl: $('#context-bar-url'),
    contextBarPreview: $('#context-bar-preview'),
    contextBarToggle: $('#context-bar-toggle'),
    // 音频转写
    uploadZone: $('#upload-zone'),
    audioFileInput: $('#audio-file-input'),
    transcribeProgress: $('#transcribe-progress'),
    transcribeResult: $('#transcribe-result'),
    transcribeText: $('#transcribe-text'),
    transcribeChars: $('#transcribe-chars'),
    btnUseAsSubtitles: $('#btn-use-as-subtitles'),
    transcribeHistorySelect: $('#transcribe-history-select'),
    themeToggle: $('#theme-toggle'),
  };

  // ─── 主题 ──────────────────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem('bb-theme');
    if (saved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      dom.themeToggle.textContent = '☀';
    }
    dom.themeToggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'dark' ? '' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      dom.themeToggle.textContent = next === 'dark' ? '☀' : '☾';
      localStorage.setItem('bb-theme', next || 'light');
    });
  }

  // ─── Toast 通知 ────────────────────────────────────────
  function showToast(message, type, duration) {
    type = type || 'info';
    duration = duration || 3000;
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function() {
      toast.style.animation = 'toast-out 0.3s ease forwards';
      setTimeout(function() { toast.remove(); }, 300);
    }, duration);
  }

  // ─── 导航切换 ──────────────────────────────────────────
  $$('.nav-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      switchPage(btn.dataset.page);
    });
  });

  function switchPage(name) {
    $$('.nav-btn').forEach(function(b) {
      b.classList.toggle('active', b.dataset.page === name);
    });
    $$('.page').forEach(function(p) {
      p.classList.toggle('active', p.id === 'page-' + name);
    });
    if (name === 'tabs') loadTabs();
    if (name === 'capture') updateHistoryDropdown();
    if (name === 'chat') updateContextBar();
    if (name === 'transcribe') loadTranscribeHistory();
    if (name === 'save') {
      // 刷新保存表单 (含摘要预填)
      if (state.currentCapture) {
        updateSaveForm(state.currentCapture);
        // 预填 AI 摘要 (从聊天中生成的)
        if (state.generatedSummary) {
          var summaryEl = document.getElementById('save-summary');
          if (summaryEl) {
            summaryEl.value = state.generatedSummary;
            showToast('摘要已从讨论中自动填入', 'info', 2500);
          }
        }
      }
    }
  }

  // ─── 状态检查 ──────────────────────────────────────────
  async function checkStatus() {
    dom.statusDot.className = 'status-dot checking';
    dom.statusText.textContent = '检查中...';
    try {
      var res = await fetch('/api/status');
      var data = await res.json();
      dom.statusDot.className = data.status === 'ok' ? 'status-dot online' : 'status-dot offline';
      if (data.cdp_connected) {
        dom.statusText.textContent = 'Chrome CDP (' + data.cdp_tab_count + ' 标签页)';
      } else {
        dom.statusText.textContent = 'Flask 在线';
      }
      dom.btnShutdown.disabled = false;
    } catch (e) {
      dom.statusDot.className = 'status-dot offline';
      dom.statusText.textContent = '服务离线 - 运行 启动.bat';
      dom.btnShutdown.disabled = true;
    }
  }

  // 关闭服务端
  dom.btnShutdown.addEventListener('click', async function() {
    if (!confirm('确定要关闭 Flask 服务端吗？')) return;
    dom.btnShutdown.disabled = true;
    dom.btnShutdown.textContent = '...';
    try {
      await fetch('/api/shutdown', { method: 'POST' });
    } catch (e) {
      // 服务端关闭后请求会失败, 这是正常的
    }
    setTimeout(function() {
      dom.statusDot.className = 'status-dot offline';
      dom.statusText.textContent = '服务已关闭 - 双击 启动.bat 重启';
      dom.btnShutdown.disabled = true;
      dom.btnShutdown.textContent = '⏻';
    }, 1000);
  });

  // ─── 标签页列表 ────────────────────────────────────────
  async function loadTabs() {
    dom.tabList.innerHTML = '<div class="loading">加载中...</div>';
    try {
      var res = await fetch('/api/tabs');
      var data = await res.json();
      state.tabs = data.tabs || [];
      if (!state.tabs.length) {
        dom.tabList.innerHTML = '<div class="empty-state">CDP 标签页不可用<br><small>请使用 Chrome 扩展进行捕获。<br>右键扩展图标 → 检查弹出内容 → 点击捕获</small></div>';
        return;
      }
      renderTabList(state.tabs);
    } catch (e) {
      dom.tabList.innerHTML = '<div class="error-message">加载失败: ' + e.message + '</div>';
    }
  }

  function renderTabList(tabs) {
    dom.tabList.innerHTML = '';
    tabs.forEach(function(tab) {
      var el = document.createElement('div');
      el.className = 'tab-item';
      if (tab.id === state.selectedTabId) el.classList.add('selected');
      el.innerHTML =
        '<img class="tab-favicon" src="' + (tab.favicon || 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><rect width=%2216%22 height=%2216%22 fill=%22%23ccc%22/></svg>') + '">' +
        '<div class="tab-info">' +
          '<div class="tab-title">' + escapeHtml(tab.title || '无标题') + '</div>' +
          '<div class="tab-url">' + escapeHtml(tab.url || '') + '</div>' +
        '</div>' +
        '<div class="tab-actions">' +
          '<button class="btn-small capture-this" data-id="' + tab.id + '">捕获</button>' +
        '</div>';
      el.addEventListener('click', function(e) {
        if (e.target.closest('.capture-this')) return;
        state.selectedTabId = tab.id;
        $$('.tab-item').forEach(function(t) { t.classList.remove('selected'); });
        el.classList.add('selected');
        showTabPreview(tab);
      });
      el.querySelector('.capture-this').addEventListener('click', function(e) {
        e.stopPropagation();
        state.selectedTabId = tab.id;
        $$('.tab-item').forEach(function(t) { t.classList.remove('selected'); });
        el.classList.add('selected');
        doCapture(tab.id);
      });
      dom.tabList.appendChild(el);
    });
  }

  // ─── 标签页搜索 ────────────────────────────────────────
  dom.tabSearch.addEventListener('input', function() {
    var q = dom.tabSearch.value.toLowerCase();
    $$('.tab-item').forEach(function(el) {
      var title = (el.querySelector('.tab-title').textContent || '').toLowerCase();
      var url = (el.querySelector('.tab-url').textContent || '').toLowerCase();
      el.style.display = (title.indexOf(q) >= 0 || url.indexOf(q) >= 0) ? '' : 'none';
    });
  });

  // ─── 标签页预览 ────────────────────────────────────────
  function showTabPreview(tab) {
    dom.captureResult.innerHTML =
      '<div class="capture-card">' +
        '<div class="capture-meta">' +
          '<div class="cap-title">' + escapeHtml(tab.title) + '</div>' +
          '<div class="cap-url">' + escapeHtml(tab.url) + '</div>' +
        '</div>' +
        '<div class="empty-state">点击「捕获」提取此页面内容</div>' +
      '</div>';
    dom.captureActions.style.display = 'none';
    dom.btnCapture.textContent = '捕获当前标签页';
    dom.btnCapture.disabled = false;
    switchPage('capture');
  }

  // ─── 进度指示器 ────────────────────────────────────────
  function showProgress(container, message) {
    container.innerHTML =
      '<div class="progress-container">' +
        '<div class="progress-track"><div class="progress-fill"></div></div>' +
        '<div class="progress-text">' + (message || '处理中...') + '</div>' +
      '</div>';
  }

  // ─── 捕获 ──────────────────────────────────────────────
  async function doCapture(tabId) {
    showProgress(dom.captureResult, '正在提取页面内容...');
    dom.captureActions.style.display = 'none';
    dom.btnCapture.disabled = true;

    try {
      var res = await fetch('/api/capture', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tab_id: tabId}),
      });
      var data = await res.json();

      if (data.error) {
        dom.captureResult.innerHTML = '<div class="error-message">捕获失败: ' + escapeHtml(data.error) + '</div>';
        dom.btnCapture.disabled = false;
        showToast('捕获失败: ' + data.error, 'error');
        return;
      }

      state.currentCapture = data;
      displayCapture(data);

      if (data._from_cache) {
        showToast('从缓存加载', 'info', 1500);
      } else {
        showToast('捕获完成', 'success');
      }
    } catch (e) {
      dom.captureResult.innerHTML = '<div class="error-message">请求失败: ' + escapeHtml(e.message) + '</div>';
      dom.btnCapture.disabled = false;
      showToast('请求失败: ' + e.message, 'error');
    }
  }

  function displayCapture(data) {
    var text = data.text || data.markdown || data.modal_content || data.plain_text || '';
    var isModal = data.has_modal;
    var authorInfo = data.author ? '<div class="cap-author">作者: ' + escapeHtml(data.author) + '</div>' : '';

    // Markdown 渲染 (marked.js)
    var renderedHtml;
    try {
      renderedHtml = marked.parse(text);
    } catch (e) {
      renderedHtml = '<pre>' + escapeHtml(text) + '</pre>';
    }

    dom.captureResult.innerHTML =
      '<div class="capture-card">' +
        '<div class="capture-meta">' +
          '<div class="cap-title">' + escapeHtml(data.title || '无标题') + '</div>' +
          '<div class="cap-url">' + escapeHtml(data.url || '') + '</div>' +
          '<div class="cap-time">' +
            '捕获时间: ' + (data.captured_at || '') +
            (isModal ? '<span class="capture-modal-badge">浮层模式</span>' : '') +
            '<span class="source-tag' + (isModal ? ' modal' : '') + '">' + (isModal ? '浮层' : '页面') + '内容</span>' +
          '</div>' + authorInfo +
        '</div>' +
        '<div class="capture-content rendered">' + renderedHtml + '</div>' +
      '</div>';

    dom.captureSource.textContent = isModal ? '浮层捕获' : '页面捕获';
    dom.captureSource.className = 'source-tag' + (isModal ? ' modal' : '');
    dom.captureActions.style.display = 'flex';
    dom.btnCapture.disabled = false;
    dom.btnCapture.textContent = '重新捕获';

    // 字幕状态提示
    if (data.hard_embedded_subs) {
      var subStatus = data.subtitle_status || 'unknown';
      var noticeHtml = '';
      if (subStatus === 'hard_embedded') {
        noticeHtml =
          '<div class="hard-sub-notice" style="flex-basis:100%;margin-top:8px;padding:10px 14px;background:var(--warning-bg);border:1px solid var(--warning);border-radius:6px;font-size:12px;color:var(--warning)">' +
            '[硬字幕确认] 该视频无AI/CC字幕，字幕为画面内嵌。<br>' +
            '请用唧唧Down下载视频文件 → <a href="#" id="goto-transcribe" style="color:var(--accent)">转到「转写」页</a>上传视频自动OCR提取字幕' +
            '</div>';
      } else {
        noticeHtml =
          '<div class="hard-sub-notice" style="flex-basis:100%;margin-top:8px;padding:10px 14px;background:var(--warning-bg);border:1px solid var(--warning);border-radius:6px;font-size:12px;color:var(--warning)">' +
            '[字幕不可用] 未能获取字幕文本。<br>' +
            '可尝试用唧唧Down下载视频 → <a href="#" id="goto-transcribe" style="color:var(--accent)">转到「转写」页</a>上传后自动提取字幕' +
            '</div>';
      }
      dom.captureActions.insertAdjacentHTML('beforeend', noticeHtml);
      document.getElementById('goto-transcribe').addEventListener('click', function(e) {
        e.preventDefault();
        switchPage('transcribe');
      });
    }

    // 添加到历史
    addToHistory(data);
    updateHistoryDropdown();
    updateSaveForm(data);
    updateContextBar();   // 如果用户在讨论页, 刷新上下文栏
    switchPage('capture');
  }

  // ─── 捕获历史 ──────────────────────────────────────────
  function addToHistory(data) {
    var entry = {
      id: data.id || null,       // 服务端分配的持久化 ID
      title: data.title || '无标题',
      url: data.url || '',
      text: data.text || data.markdown || data.modal_content || data.plain_text || '',
      captured_at: data.captured_at || data.created_at || new Date().toISOString(),
      has_modal: data.has_modal,
      author: data.author || '',
      metadata: data.metadata || {},
      _ts: Date.now(),
      _from_api: false,          // 当前会话捕获, 含完整文本
    };
    // 去重: 相同 URL 在 5 秒内不重复添加
    if (captureHistory.length > 0) {
      var last = captureHistory[0];
      if (last.url === entry.url && Date.now() - last._ts < 5000) {
        captureHistory[0] = entry;  // 更新
        return;
      }
    }
    captureHistory.unshift(entry);
    if (captureHistory.length > MAX_HISTORY) captureHistory.pop();
  }

  function updateHistoryDropdown() {
    if (captureHistory.length === 0) {
      dom.historyBar.style.display = 'none';
      return;
    }
    dom.historyBar.style.display = 'flex';
    dom.historySelect.innerHTML = '<option value="">-- 历史记录 (' + captureHistory.length + '条) --</option>';
    captureHistory.forEach(function(h, i) {
      var opt = document.createElement('option');
      opt.value = i;
      var timeStr = h.captured_at || h.created_at || '';
      opt.textContent = (h.title || '无标题').substring(0, 60) + ' (' + timeStr.substring(0, 19) + ')';
      dom.historySelect.appendChild(opt);
    });
  }

  // ─── 上下文栏 ──────────────────────────────────────────
  function updateContextBar() {
    if (!state.currentCapture) {
      dom.chatContextBar.style.display = 'none';
      return;
    }
    var cap = state.currentCapture;
    dom.chatContextBar.style.display = '';
    dom.contextBarTitle.textContent = cap.title || '无标题';
    dom.contextBarUrl.textContent = cap.url || '';
    dom.contextBarUrl.href = cap.url || '#';
    var preview = (cap.text || cap.markdown || cap.plain_text || '').substring(0, 200);
    dom.contextBarPreview.textContent = preview + (preview.length >= 200 ? '...' : '');
  }

  // 上下文栏折叠/展开
  dom.contextBarToggle.addEventListener('click', function() {
    dom.chatContextBar.classList.toggle('collapsed');
    var collapsed = dom.chatContextBar.classList.contains('collapsed');
    dom.contextBarToggle.textContent = collapsed ? '▶' : '▼';
  });

  dom.historySelect.addEventListener('change', function() {
    var idx = parseInt(dom.historySelect.value);
    if (isNaN(idx) || !captureHistory[idx]) return;
    dom.historySelect.value = '';
    var h = captureHistory[idx];

    if (h.text) {
      // 当前会话捕获, 直接使用 (含完整文本)
      var restored = {
        title: h.title,
        url: h.url,
        text: h.text,
        modal_content: h.has_modal ? h.text : undefined,
        has_modal: h.has_modal,
        author: h.author,
        metadata: h.metadata,
        captured_at: h.captured_at,
      };
      state.currentCapture = restored;
      displayCapture(restored);
      showToast('已恢复历史记录', 'info', 2000);
    } else if (h.id && h._from_api) {
      // 持久化条目, 按需加载完整内容
      loadHistoryDetail(h.id);
    }
  });

  async function loadHistoryDetail(captureId) {
    try {
      var resp = await fetch('/api/captures/' + captureId);
      if (!resp.ok) {
        showToast('加载历史记录失败', 'error');
        return;
      }
      var detail = await resp.json();
      detail.text = detail.markdown || detail.plain_text || '';
      state.currentCapture = detail;
      displayCapture(detail);
      showToast('已加载历史记录', 'success', 2000);
    } catch (e) {
      showToast('加载历史记录失败: ' + e.message, 'error');
    }
  }

  // ─── 保存表单 ──────────────────────────────────────────
  function updateSaveForm(data) {
    if (!data) {
      dom.saveForm.innerHTML = '<div class="empty-state">先捕获内容，再来保存</div>';
      return;
    }
    var text = data.text || data.markdown || '';
    dom.saveForm.innerHTML =
      '<div class="form-group"><label>标题</label>' +
        '<input id="save-title" value="' + escapeAttr(data.title || '') + '">' +
      '</div>' +
      '<div class="form-group"><label>来源 URL</label>' +
        '<input id="save-url" value="' + escapeAttr(data.url || '') + '">' +
      '</div>' +
      '<div class="form-group"><label>内容预览（可修改）</label>' +
        '<textarea id="save-content" rows="6">' + escapeHtml(text.substring(0, 5000)) + '</textarea>' +
      '</div>' +
      '<div class="form-group"><label>AI 摘要</label>' +
        '<textarea id="save-summary" rows="3" placeholder="点击「生成摘要」自动生成..."></textarea>' +
      '</div>' +
      '<div class="checkbox-group">' +
        '<input type="checkbox" id="save-with-wiki"><label for="save-with-wiki">同时创建 wiki 摘要页面</label>' +
      '</div>' +
      '<div style="display:flex;gap:8px">' +
        '<button id="btn-do-save" class="btn-primary">保存到外脑</button>' +
        '<button id="btn-gen-summary" class="btn-small">生成摘要</button>' +
      '</div>' +
      '<div id="save-result" style="margin-top:12px"></div>';

    document.getElementById('btn-do-save').addEventListener('click', doSave);
    document.getElementById('btn-gen-summary').addEventListener('click', genSummary);

    // 预填 AI 摘要 (如果聊天或保存页已生成)
    if (state.generatedSummary) {
      var summaryEl = document.getElementById('save-summary');
      if (summaryEl) summaryEl.value = state.generatedSummary;
    }
  }

  async function genSummary() {
    var text = document.getElementById('save-content').value;
    if (!text) return;
    var btn = document.getElementById('btn-gen-summary');
    btn.disabled = true;
    btn.textContent = '生成中...';
    try {
      var res = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          message: '请用中文生成这篇内容的摘要，包含核心论点、关键数据和要点。',
          context: text.substring(0, 4000),
        }),
      });
      var data = await res.json();
      if (data.reply) {
        document.getElementById('save-summary').value = data.reply;
        state.generatedSummary = data.reply;  // 双向同步: 保存页 → 聊天
      }
    } catch (e) {
      document.getElementById('save-result').innerHTML =
        '<div class="error-message">生成失败: ' + escapeHtml(e.message) + '</div>';
    }
    btn.disabled = false;
    btn.textContent = '生成摘要';
  }

  async function doSave() {
    var btn = document.getElementById('btn-do-save');
    btn.disabled = true;
    btn.textContent = '保存中...';
    try {
      var res = await fetch('/api/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          url: document.getElementById('save-url').value,
          title: document.getElementById('save-title').value,
          markdown: document.getElementById('save-content').value,
          with_wiki: document.getElementById('save-with-wiki').checked,
          summary: document.getElementById('save-summary').value,
          tags: ['clippings'],
        }),
      });
      var data = await res.json();
      var el = document.getElementById('save-result');
      if (data.success) {
        el.innerHTML =
          '<div style="padding:12px;background:var(--success-bg);border-radius:6px;color:var(--success)">' +
            '保存成功！<br>文件: ' + escapeHtml(data.raw_file || '') + '<br>' +
            (data.wiki_file ? 'Wiki: ' + escapeHtml(data.wiki_file) : '') +
          '</div>';
        showToast('保存成功', 'success');
      } else {
        el.innerHTML = '<div class="error-message">保存失败: ' + escapeHtml(data.error || '未知错误') + '</div>';
        showToast('保存失败', 'error');
      }
    } catch (e) {
      document.getElementById('save-result').innerHTML =
        '<div class="error-message">请求失败: ' + escapeHtml(e.message) + '</div>';
    }
    btn.disabled = false;
    btn.textContent = '保存到外脑';
  }

  // ─── 流式聊天 SSE ──────────────────────────────────────
  function addChatMessage(role, content) {
    var el = document.createElement('div');
    el.className = 'msg ' + role;
    var avatar = role === 'user' ? '你' : 'AI';
    el.innerHTML =
      '<div class="msg-avatar">' + avatar + '</div>' +
      '<div class="msg-bubble">' + content + '</div>';
    dom.chatMessages.appendChild(el);
    dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
    return el;  // 返回元素引用，用于流式更新
  }

  async function sendChatMessage(message) {
    if (!message.trim()) return;
    addChatMessage('user', message);
    dom.chatInput.value = '';

    // 构建上下文
    var context = '';
    if (dom.chatContext.checked && state.currentCapture) {
      context = state.currentCapture.text || '';
    }

    // 创建 AI 消息占位
    var aiEl = addChatMessage('assistant', '思考中...');
    var bubble = aiEl.querySelector('.msg-bubble');
    var fullText = '';

    try {
      var res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          message: message,
          context: context.substring(0, 8000),
        }),
      });

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {stream: true});

        // 解析 SSE 行
        var lines = buffer.split('\n');
        buffer = lines.pop() || '';  // 保留未完成的行

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.indexOf('data: ') === 0) {
            var payload = line.substring(6);
            if (payload === '[DONE]') {
              // 最终渲染
              try {
                bubble.innerHTML = marked.parse(fullText);
              } catch (e) {
                bubble.textContent = fullText;
              }
              state.chatHistory.push({role: 'assistant', content: fullText});
              state.generatedSummary = fullText;  // 供保存页预填
              return;
            }
            try {
              var parsed = JSON.parse(payload);
              if (parsed.text) {
                fullText += parsed.text;
                bubble.textContent = fullText;  // 逐 token 显示纯文本
              }
              if (parsed.error) {
                bubble.textContent = '[错误] ' + parsed.error;
                return;
              }
            } catch (e) {
              // 忽略解析错误的行
            }
          }
        }
      }

      // 流结束，最终渲染 Markdown
      try {
        bubble.innerHTML = marked.parse(fullText);
      } catch (e) {
        bubble.textContent = fullText;
      }
      state.chatHistory.push({role: 'assistant', content: fullText});
      state.generatedSummary = fullText;  // 供保存页预填

    } catch (e) {
      bubble.textContent = '[请求失败] ' + e.message;
      showToast('聊天请求失败', 'error');
    }
    dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
  }

  // ─── 键盘快捷键 ────────────────────────────────────────
  document.addEventListener('keydown', function(e) {
    // 在输入框中仅保留 Escape
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      if (e.key === 'Escape') e.target.blur();
      return;
    }

    var ctrl = e.ctrlKey || e.metaKey;

    if (ctrl && e.key === 'r') {
      e.preventDefault();
      loadTabs();
      showToast('标签页已刷新', 'info', 1500);
    } else if (ctrl && e.key === 'Enter') {
      e.preventDefault();
      if (state.selectedTabId) doCapture(state.selectedTabId);
    } else if (ctrl && e.key === 'k') {
      e.preventDefault();
      switchPage('tabs');
      dom.tabSearch.focus();
    } else if (ctrl && e.key === 'l') {
      e.preventDefault();
      switchPage('chat');
      dom.chatInput.focus();
    } else if (ctrl && e.key === 't') {
      e.preventDefault();
      dom.themeToggle.click();
    } else if (ctrl && e.key >= '1' && e.key <= '5') {
      e.preventDefault();
      var pages = ['tabs', 'capture', 'chat', 'transcribe', 'save'];
      switchPage(pages[parseInt(e.key) - 1]);
    }
  });

  // ─── 事件绑定 ──────────────────────────────────────────
  dom.btnCapture.addEventListener('click', function() {
    if (state.selectedTabId) doCapture(state.selectedTabId);
  });

  dom.btnRefreshTabs.addEventListener('click', loadTabs);

  dom.btnSummary.addEventListener('click', function() {
    if (!state.currentCapture) return;
    sendChatMessage('请总结一下这个页面的核心内容，列出关键要点。');
    switchPage('chat');
  });

  dom.btnChatAbout.addEventListener('click', function() {
    if (!state.currentCapture) return;
    switchPage('chat');
    dom.chatInput.focus();
  });

  dom.btnSaveCapture.addEventListener('click', function() {
    if (!state.currentCapture) return;
    switchPage('save');
  });

  dom.btnSend.addEventListener('click', function() {
    sendChatMessage(dom.chatInput.value);
  });
  dom.chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage(dom.chatInput.value);
    }
  });

  document.querySelectorAll('.quick-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      sendChatMessage(btn.dataset.q);
    });
  });

  dom.btnClearChat.addEventListener('click', function() {
    dom.chatMessages.innerHTML = '<div class="empty-state">聊天已清空</div>';
    state.chatHistory = [];
  });

  // ─── 音频转写 ──────────────────────────────────────────

  // 转写历史
  var _transcribeHistoryLoaded = false;

  async function loadTranscribeHistory() {
    if (_transcribeHistoryLoaded) return;
    _transcribeHistoryLoaded = true;
    try {
      var resp = await fetch('/api/transcriptions');
      if (!resp.ok) return;
      var items = await resp.json();
      if (!items || !items.length) return;
      var sel = dom.transcribeHistorySelect;
      sel.innerHTML = '<option value="">-- 转写历史 (' + items.length + '条) --</option>';
      items.forEach(function(item, i) {
        var opt = document.createElement('option');
        opt.value = item.id;
        var timeStr = (item.created_at || '').substring(0, 19);
        var methodLabel = item.method || '';
        opt.textContent = timeStr + ' | ' + item.char_count + '字 | ' + methodLabel;
        sel.appendChild(opt);
      });
      sel.style.display = '';
    } catch (e) {
      console.warn('Load transcribe history failed:', e);
    }
  }

  dom.transcribeHistorySelect.addEventListener('change', async function() {
    var id = dom.transcribeHistorySelect.value;
    if (!id) return;
    dom.transcribeHistorySelect.value = '';
    try {
      var resp = await fetch('/api/transcriptions/' + id);
      if (!resp.ok) { showToast('加载失败', 'error'); return; }
      var item = await resp.json();
      dom.transcribeText.value = item.text;
      dom.transcribeChars.textContent = item.char_count;
      dom.transcribeResult.style.display = '';
      dom.uploadZone.style.display = 'none';
      showToast('已恢复: ' + item.char_count + '字 | ' + item.method, 'success');
    } catch (e) {
      showToast('加载失败: ' + e.message, 'error');
    }
  });

  // 上传区域: 点击选择文件
  dom.uploadZone.addEventListener('click', function() {
    dom.audioFileInput.click();
  });

  // 拖拽上传
  dom.uploadZone.addEventListener('dragover', function(e) {
    e.preventDefault();
    dom.uploadZone.classList.add('drag-over');
  });
  dom.uploadZone.addEventListener('dragleave', function() {
    dom.uploadZone.classList.remove('drag-over');
  });
  dom.uploadZone.addEventListener('drop', function(e) {
    e.preventDefault();
    dom.uploadZone.classList.remove('drag-over');
    var file = e.dataTransfer.files[0];
    if (file) handleTranscribeFile(file);
  });

  dom.audioFileInput.addEventListener('change', function() {
    var file = dom.audioFileInput.files[0];
    if (file) handleTranscribeFile(file);
  });

  var _transcribeAbortController = null;  // 用于取消转写

  async function handleTranscribeFile(file) {
    var maxSize = 500 * 1024 * 1024;
    if (file.size > maxSize) {
      showToast('文件太大 (最大 500MB)', 'error');
      return;
    }

    // 取消之前的转写
    if (_transcribeAbortController) {
      _transcribeAbortController.abort();
    }
    _transcribeAbortController = new AbortController();

    // 显示进度
    dom.uploadZone.style.display = 'none';
    dom.transcribeResult.style.display = 'none';
    dom.transcribeProgress.style.display = '';
    dom.transcribeChars.textContent = '0';
    setTranscribeProgress(0, '正在上传...');

    var formData = new FormData();
    formData.append('file', file);

    try {
      var resp = await fetch('/api/transcribe', {
        method: 'POST',
        body: formData,
        signal: _transcribeAbortController.signal,
      });

      if (!resp.ok) {
        var errText = await resp.text();
        showToast('转写失败: ' + resp.status, 'error');
        dom.uploadZone.style.display = '';
        dom.transcribeProgress.style.display = 'none';
        return;
      }

      // 读取 SSE 事件流
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {stream: true});
        var lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.indexOf('data: ') !== 0) continue;
          var payload = line.substring(6);

          try {
            var evt = JSON.parse(payload);

            if (evt.error) {
              showToast('转写失败: ' + evt.error, 'error');
              dom.uploadZone.style.display = '';
              dom.transcribeProgress.style.display = 'none';
              return;
            }

            if (evt.done) {
              // 完成
              setTranscribeProgress(100, '完成!');
              dom.transcribeProgress.style.display = 'none';
              dom.transcribeText.value = evt.text;
              dom.transcribeChars.textContent = evt.char_count;
              dom.transcribeResult.style.display = '';
              showToast('转写完成! ' + evt.char_count + ' 字 | ' + evt.segment_count + ' 条', 'success');
              state.generatedSummary = evt.text;
              // 刷新历史列表
              _transcribeHistoryLoaded = false;
              loadTranscribeHistory();
              return;
            }

            // 进度更新
            if (evt.percent !== undefined) {
              var stageLabel = evt.stage === 'ocr' ? 'OCR 识别中' : '提取帧中';
              setTranscribeProgress(evt.percent, stageLabel + ' (' + evt.current + '/' + evt.total + ')');
            } else if (evt.stage === 'init') {
              setTranscribeProgress(0, evt.message);
            }
          } catch (e) {
            // 跳过解析失败的行
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        showToast('请求失败: ' + e.message, 'error');
      }
      dom.uploadZone.style.display = '';
      dom.transcribeProgress.style.display = 'none';
    }
  }

  function setTranscribeProgress(percent, message) {
    var fill = dom.transcribeProgress.querySelector('.progress-fill');
    var text = dom.transcribeProgress.querySelector('.progress-text');
    if (fill) fill.style.width = percent + '%';
    if (text) text.textContent = message;
  }

  // "应用为字幕" 按钮 — 把转写文本设为当前捕获的字幕
  dom.btnUseAsSubtitles.addEventListener('click', function() {
    var text = dom.transcribeText.value;
    if (!text || !state.currentCapture) {
      showToast('没有捕获内容可关联', 'error');
      return;
    }
    // 更新当前捕获
    state.currentCapture.subtitles = text;
    state.currentCapture.text = (state.currentCapture.text || '') +
      '\n\n## 语音转写\n\n' + text;
    state.currentCapture.plain_text = state.currentCapture.text;
    state.currentCapture.has_subtitles = true;
    displayCapture(state.currentCapture);
    showToast('字幕已应用!', 'success');
    switchPage('capture');
  });
  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ─── 初始化 ────────────────────────────────────────────
  async function init() {
    initTheme();
    await checkStatus();

    // 从服务端加载持久化的捕获历史
    try {
      var histResp = await fetch('/api/captures?limit=20');
      if (histResp.ok) {
        var histData = await histResp.json();
        if (histData.captures && histData.captures.length > 0) {
          captureHistory = histData.captures.map(function(c) {
            return {
              id: c.id,
              title: c.title || '无标题',
              url: c.url || '',
              text: '',   // 持久化条目不含完整文本, 按需加载
              captured_at: c.created_at || '',
              preview: c.preview || '',
              content_type: c.content_type,
              captured_via: c.captured_via,
              _from_api: true,
            };
          });
          updateHistoryDropdown();
        }
      }
    } catch (e) {
      console.warn('[WebUI] Failed to load capture history:', e);
    }

    // 优先拉取扩展捕获的最新内容 (服务端存储)
    try {
      var lcResp = await fetch('/api/last-capture');
      if (lcResp.ok) {
        var lcData = await lcResp.json();
        if (!lcData.error) {
          // 字段映射: API 返回 markdown, 前端用 text
          lcData.text = lcData.markdown || lcData.text || '';
          state.currentCapture = lcData;
          displayCapture(lcData);
          console.log('[WebUI] Loaded last capture from server');
        }
      }
    } catch (e) {
      // 没有捕获内容, 正常
    }

    await loadTabs();
    setInterval(checkStatus, 10000);
  }

  init();
})();
