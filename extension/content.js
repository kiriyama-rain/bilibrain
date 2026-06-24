/**
 * Browser Brain — Content Script
 * ===============================
 * 注入到每个页面, 负责内容提取和元数据收集.
 *
 * Phase 2 预留:
 *   - detectContentType(): 判断页面是网页/视频/音频
 *   - 视频页面提取 video URL、duration、captions 等
 *   - extractVideoMeta(): 为 Phase 2 多模态处理准备元数据
 */
'use strict';

// ─── 消息监听 ──────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'extract') {
    // 异步提取 (含字幕 API 调用)
    extractPageContent().then(result => sendResponse(result));
    return true;  // 保持 sendResponse 有效
  }
  if (msg.action === 'ping') {
    sendResponse({ pong: true });
  }
});

// ─── 内容提取 ──────────────────────────────────────────────

async function extractPageContent() {
  try {
    const url = location.href;
    const title = document.title || '';
    const contentType = detectContentType();

    const metadata = {
      description: getMeta('description')
        || getMeta('og:description', 'property') || '',
      author: getMeta('author')
        || getMeta('article:author', 'property') || '',
      published: getMeta('article:published_time', 'property')
        || getMeta('date') || '',
      keywords: getMeta('keywords') || '',
      siteName: getMeta('og:site_name', 'property')
        || getMeta('application-name') || '',
      ogImage: getMeta('og:image', 'property') || '',
      ogTitle: getMeta('og:title', 'property') || '',
    };

    const bodyHTML = extractBodyHTML();
    const bodyText = extractBodyText();

    // Phase 2: 视频元数据 + 字幕提取
    let mediaMeta = null;
    if (contentType === 'video' || contentType === 'audio') {
      console.log('[BB] 视频页, 提取字幕...');
      mediaMeta = extractMediaMeta(contentType);
      const subsText = await fetchSubtitles(url, contentType, mediaMeta);
      if (subsText) {
        console.log('[BB] 字幕提取成功:', subsText.length, '字');
        mediaMeta.subtitle_text = subsText;
        mediaMeta.subtitle_length = subsText.length;
      } else {
        console.log('[BB] 字幕提取失败或无字幕');
      }
    } else {
      console.log('[BB] 非视频页, 跳过字幕提取');
    }

    return {
      url, title, content_type: contentType,
      metadata,
      body_html: bodyHTML,
      body_text: bodyText.substring(0, 100000),
      text_length: bodyText.length,
      media_meta: mediaMeta,
      extracted_at: new Date().toISOString(),
    };
  } catch (e) {
    return { error: `提取失败: ${e.message}` };
  }
}

// ─── 内容类型检测 (Phase 2 关键) ──────────────────────────

function detectContentType() {
  const url = location.href.toLowerCase();
  const host = location.hostname.toLowerCase();

  // 已知视频平台
  const videoDomains = [
    'youtube.com', 'youtu.be', 'bilibili.com',
    'douyin.com', 'tiktok.com', 'iqiyi.com',
    'youku.com', 'v.qq.com', 'ixigua.com',
    'huya.com', 'douyu.com', 'kuaishou.com',
    'twitch.tv', 'vimeo.com',
  ];
  for (const d of videoDomains) {
    if (host.includes(d)) return 'video';
  }

  // URL 路径模式
  if (/\/video\/|\/watch|\/play\/|\/live\/|\/tv\//.test(url)) return 'video';

  // 页面内 video 元素检测
  const videos = document.querySelectorAll('video');
  if (videos.length > 0) {
    for (const v of videos) {
      if (v.duration && v.duration > 10) return 'video';
    }
  }

  // 音频平台
  const audioDomains = ['music.163.com', 'y.qq.com', 'kugou.com', 'spotify.com', 'soundcloud.com'];
  for (const d of audioDomains) {
    if (host.includes(d)) return 'audio';
  }

  return 'webpage';
}

// ─── 视频/音频元数据提取 (Phase 2) ─────────────────────────

function extractMediaMeta(contentType) {
  const meta = { type: contentType };

  const video = document.querySelector('video');
  if (video) {
    meta.duration = video.duration || 0;
    meta.has_captions = video.textTracks?.length > 0;
  }

  try {
    const initState = window.__INITIAL_STATE__ || {};
    // B站
    if (initState.videoData) {
      const vd = initState.videoData;
      meta.title = vd.title || '';
      meta.desc = vd.desc || '';
      meta.duration = vd.duration || meta.duration;
      meta.bvid = vd.bvid || '';
      meta.cid = vd.cid || (vd.pages?.[0]?.cid) || '';
    }
    // YouTube
    if (window.ytInitialPlayerResponse?.videoDetails) {
      const vd = window.ytInitialPlayerResponse.videoDetails;
      meta.title = vd.title || '';
      meta.duration = parseInt(vd.lengthSeconds) || meta.duration;
      meta.author = vd.author || '';
    }
  } catch (e) {
    // ignore
  }

  meta.page_url = location.href;
  return meta;
}

// ─── HTML 正文提取 ─────────────────────────────────────────

function extractBodyHTML() {
  // 克隆 body, 移除无用元素
  const body = document.body.cloneNode(true);
  const remove = 'script, style, noscript, iframe, svg, canvas, template, nav, footer, header, aside, form, button, [aria-hidden="true"]';
  body.querySelectorAll(remove).forEach(el => el.remove());

  // 移除常见广告/侧栏
  const killClasses = [
    '.advertisement', '.ad-', '.ads', '.sidebar', '.widget',
    '.comment', '.comment-list', '.related', '.recommend',
    '.social-share', '.share-bar', '.toolbar', '.cookie',
    '[role=complementary]', '[role=banner]', '[role=navigation]',
  ];
  killClasses.forEach(sel => {
    try { body.querySelectorAll(sel).forEach(el => el.remove()); } catch (e) {}
  });

  return body.outerHTML.substring(0, 500000);
}

function extractBodyText() {
  // 优先 <article>
  const article = document.querySelector('article');
  if (article) {
    const text = article.innerText || '';
    if (text.length > 200) return text;
  }
  // <main>
  const main = document.querySelector('main');
  if (main) {
    const text = main.innerText || '';
    if (text.length > 200) return text;
  }
  // 最长文本块
  let best = '', bestLen = 0;
  document.querySelectorAll('div, section, p').forEach(el => {
    const len = (el.innerText || '').length;
    if (len > bestLen) { bestLen = len; best = el.innerText || ''; }
  });
  if (bestLen > 300) return best;
  // body 兜底
  return document.body.innerText || '';
}

// ─── 元数据辅助 ────────────────────────────────────────────

function getMeta(name, attr = 'name') {
  const attrSel = attr === 'property' ? `meta[property="${name}"]` : `meta[name="${name}"]`;
  const el = document.querySelector(attrSel);
  return el ? (el.getAttribute('content') || el.content || '') : '';
}

// ─── Phase 2: 字幕提取 (浏览器 cookie 直接调用平台 API) ────

async function fetchSubtitles(url, contentType, mediaMeta) {
  const host = (url || '').toLowerCase();
  console.log('[BB] fetchSubtitles host=', host);
  if (host.includes('bilibili.com')) {
    return await fetchBilibiliSubtitles(mediaMeta);
  }
  if (host.includes('youtube.com') || host.includes('youtu.be')) {
    return await fetchYouTubeSubtitles(url, mediaMeta);
  }
  console.log('[BB] 非B站/YouTube, 跳过字幕');
  return null;
}

async function fetchBilibiliSubtitles(mediaMeta) {
  try {
    console.log('[BB] B站字幕提取开始...');

    // 从 URL 提取 bvid
    const m = location.pathname.match(/\/video\/(BV[A-Za-z0-9]+)/);
    const bvid = m ? m[1] : (mediaMeta?.bvid || '');
    console.log('[BB] bvid=', bvid);

    if (!bvid) {
      console.log('[BB] 无法提取bvid');
      return null;
    }

    // 通过 B站公开 API 获取 cid — 页面注入 fetch (自带 cookie + 绕过 CORS)
    console.log('[BB] 调 B站 API 获取视频信息...');
    const viewUrl = `https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`;
    const viewData = await fetchViaPageContext(viewUrl);
    let cid, videoInfo;
    if (viewData) {
      videoInfo = viewData || {};
      cid = String(videoInfo.cid || (videoInfo.pages?.[0]?.cid) || '');
      console.log('[BB] cid=', cid, 'title=', (videoInfo.title || '').substring(0, 30));
    } else {
      // 页面注入失败, 走 background 代理
      console.log('[BB] view API 页面注入失败, 走background代理');
      const infoResp = await chrome.runtime.sendMessage({
        action: 'fetchJSON',
        url: viewUrl,
      });
      if (!infoResp?.ok) {
        console.log('[BB] B站 API 失败:', infoResp?.error);
        return null;
      }
      videoInfo = infoResp.data?.data || {};
      cid = String(videoInfo.cid || (videoInfo.pages?.[0]?.cid) || '');
    }

    if (!cid) {
      console.log('[BB] 无法获取cid');
      return null;
    }

    const manualList = [];  // 手动字幕也在 player API 里统一获取

    // 更新 mediaMeta 中的视频信息
    if (mediaMeta && videoInfo) {
      mediaMeta.title = videoInfo.title || mediaMeta.title || '';
      mediaMeta.desc = videoInfo.desc || mediaMeta.desc || '';
      mediaMeta.duration = videoInfo.duration || mediaMeta.duration || 0;
    }

    // 通过 WBI 签名 player API 获取字幕 + 音频流
    // 注入页面脚本发请求 (页面 JS 上下文, 自动通过 CORS + cookie)
    console.log('[BB] 调 WBI player API 获取字幕+音频...');
    const signResp = await chrome.runtime.sendMessage({
      action: 'signWbiUrl',
      url: `https://api.bilibili.com/x/player/wbi/v2?bvid=${bvid}&cid=${cid}&fnval=16`,
    });
    if (!signResp?.ok) {
      console.log('[BB] WBI 签名失败:', signResp?.error);
      mediaMeta.subtitle_status = 'api_failed';
      return null;
    }
    const signedUrl = signResp.signedUrl;

    // 注入页面脚本来发请求 (避免 CORS/content script 隔离限制)
    const playerData = await fetchViaPageContext(signedUrl);
    if (!playerData) {
      console.log('[BB] player API (页面注入) 失败');
      mediaMeta.subtitle_status = 'api_failed';
      return null;
    }
    console.log('[BB] player API resp: hasDash=', !!playerData.dash,
      'dashAudio=', playerData.dash?.audio?.length || 0,
      'subs=', playerData.subtitle?.subtitles?.length || 0);

    // ── 提取音频流 URL (硬字幕降级方案) ──
    const dash = playerData.dash;
    if (dash?.audio?.length > 0) {
      const audios = dash.audio;
      const best = audios.reduce((a, b) =>
        (a.bandwidth || 0) > (b.bandwidth || 0) ? a : b
      );
      mediaMeta.bilibili_audio_url = best.base_url || best.baseUrl || '';
      mediaMeta.bilibili_audio_backups = audios.map(a =>
        a.backup_url || a.backupUrl || []
      ).flat().filter(Boolean);
      console.log('[BB] 音频流:', (best.bandwidth || 0) / 1000, 'kbps,',
        mediaMeta.bilibili_audio_backups.length, '个备用');
    } else {
      console.log('[BB] 无 DASH 音频流');
    }

    // ── 提取字幕 ──
    const subtitles = playerData.subtitle?.subtitles || [];
    console.log('[BB] 字幕列表:', subtitles.length, '个');

    if (subtitles.length === 0) {
      // API 调用成功, 但确实无软字幕 → 标记为硬字幕
      mediaMeta.subtitle_status = 'api_success_no_subs';
      console.log('[BB] API成功但无字幕 → 硬字幕视频');
      return null;
    }

    // 优先中文, 其次任何
    const sub = subtitles.find(s => /zh|ch/i.test(s.lan || s.lan_doc || ''))
      || subtitles[0];
    if (!sub?.subtitle_url) {
      mediaMeta.subtitle_status = 'api_success_no_subs';
      return null;
    }

    console.log('[BB] 下载字幕内容:', (sub.lan || sub.lan_doc || '?'));
    const subResp = await chrome.runtime.sendMessage({
      action: 'fetchJSON',
      url: (sub.subtitle_url.startsWith('//') ? 'https:' + sub.subtitle_url : sub.subtitle_url),
    });
    if (!subResp?.ok) {
      console.log('[BB] 字幕下载失败');
      mediaMeta.subtitle_status = 'api_success_no_subs';
      return null;
    }

    const items = subResp.data?.body || subResp.data || [];
    const lines = (Array.isArray(items) ? items : []).map(
      item => (item.content || '').trim()
    ).filter(t => t);
    console.log('[BB] 字幕:', lines.length, '行');
    if (lines.length > 0) {
      mediaMeta.subtitle_status = 'subs_found';
      return lines.join('\n');
    }
    mediaMeta.subtitle_status = 'api_success_no_subs';
    return null;
  } catch (e) {
    console.debug('[BB] B站字幕提取失败:', e.message);
    return null;
  }
}

async function fetchBilibiliSubtitleJSON(subtitleUrl) {
  const fullUrl = subtitleUrl.startsWith('//') ? 'https:' + subtitleUrl : subtitleUrl;
  const resp = await fetch(fullUrl);
  if (!resp.ok) return null;
  const data = await resp.json();
  // B站字幕格式: [{from, to, content}, ...] 或 {body: [...]}
  const items = data.body || data || [];
  const lines = (Array.isArray(items) ? items : []).map(
    item => (item.content || '').trim()
  ).filter(t => t);
  return lines.join('\n');
}

async function fetchYouTubeSubtitles(url, mediaMeta) {
  // YouTube 字幕来自 ytInitialPlayerResponse.captions
  try {
    const pr = window.ytInitialPlayerResponse;
    if (!pr?.captions?.playerCaptionsTracklistRenderer?.captionTracks?.length) {
      return null;
    }

    const tracks = pr.captions.playerCaptionsTracklistRenderer.captionTracks;
    // 优先中文, 其次英文, 最后第一个
    let track = tracks.find(t => t.languageCode === 'zh')
      || tracks.find(t => t.languageCode === 'en')
      || tracks[0];
    if (!track?.baseUrl) return null;

    const resp = await fetch(track.baseUrl);
    if (!resp.ok) return null;
    const xml = await resp.text();

    // YouTube 字幕是 XML: <text start=".." dur="..">content</text>
    const lines = [];
    const re = /<text[^>]*>([^<]*)<\/text>/g;
    let m;
    while ((m = re.exec(xml)) !== null) {
      const text = m[1].trim();
      if (text && text !== '&#39;' && text !== '&nbsp;') {
        lines.push(text.replace(/&amp;/g, '&').replace(/&lt;/g, '<')
                       .replace(/&gt;/g, '>').replace(/&#39;/g, "'"));
      }
    }
    return lines.join('\n');
  } catch (e) {
    console.debug('[BB] YouTube字幕提取失败:', e.message);
    return null;
  }
}


// ─── 通过 background.js 代理 fetch (带完整 cookie) ──

async function fetchViaPageContext(url, timeoutMs = 15000) {
  /**
   * 回退到 background.js 代理。
   * background.js 通过 chrome.cookies.getAll 构建完整的 Cookie header。
   */
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(null), timeoutMs);
    chrome.runtime.sendMessage({ action: 'fetchWbiJSON', url }).then(resp => {
      clearTimeout(timeout);
      resolve(resp?.ok ? (resp.data?.data || null) : null);
    }).catch(() => {
      clearTimeout(timeout);
      resolve(null);
    });
  });
}

console.log('[BrowserBrain] Content script loaded');
