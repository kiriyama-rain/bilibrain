/**
 * Browser Brain — Background Service Worker (MV3)
 * ===============================================
 * 职责: 标签页查询、消息路由、与 Flask 后端通信
 */
'use strict';

const FLASK_URL = 'http://127.0.0.1:5577';

// ─── B站 Cookie 辅助 ───────────────────────────────────
// MV3 service worker 的 fetch 不自动发送 SameSite=Lax cookie,
// 需要手动读取 chrome.cookies 并附加 Cookie header

let _biliCookie = null;
let _biliCookieTime = 0;
const COOKIE_CACHE_MS = 5 * 60 * 1000; // 5分钟缓存

async function getBiliCookieHeader() {
  const now = Date.now();
  if (_biliCookie && (now - _biliCookieTime) < COOKIE_CACHE_MS) {
    return _biliCookie;
  }
  try {
    const cookies = await chrome.cookies.getAll({ domain: '.bilibili.com' });
    if (cookies.length === 0) {
      console.warn('[BB:BG] No bilibili cookies found (not logged in?)');
      return '';
    }
    // 诊断: 检查关键 cookie
    const sessData = cookies.find(c => c.name === 'SESSDATA');
    const biliJct = cookies.find(c => c.name === 'bili_jct');
    const dedeUserID = cookies.find(c => c.name === 'DedeUserID');
    console.log('[BB:BG] Cookies:', cookies.length, 'total |',
      'SESSDATA:', sessData ? 'YES(' + (sessData.value || '').substring(0, 8) + '...)' : 'MISSING',
      'bili_jct:', biliJct ? 'YES' : 'MISSING',
      'DedeUserID:', dedeUserID ? dedeUserID.value : 'MISSING');
    _biliCookie = cookies.map(c => c.name + '=' + c.value).join('; ');
    _biliCookieTime = now;
    return _biliCookie;
  } catch (e) {
    console.warn('[BB:BG] Failed to get bilibili cookies:', e.message);
    return '';
  }
}

chrome.runtime.onInstalled.addListener(() => {
  console.log('[BB:BG] Extension installed');
});

// ─── 消息路由 ─────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  console.log('[BB:BG] onMessage:', msg.action);

  switch (msg.action) {

    case 'getTabs':
      chrome.tabs.query({}, (tabs) => {
        const filtered = tabs
          .filter(t => t.url && !t.url.startsWith('chrome://') && !t.url.startsWith('devtools://'))
          .map(t => ({
            id: t.id, title: t.title || '无标题', url: t.url || '',
            favicon: t.favIconUrl || '', active: t.active,
          }));
        sendResponse({ tabs: filtered });
      });
      return true;

    case 'activateTab':
      chrome.tabs.update(msg.tabId, { active: true });
      sendResponse({ success: true });
      break;

    case 'extractContent':
      console.log('[BB:BG] extractContent tabId=', msg.tabId);
      chrome.tabs.sendMessage(msg.tabId, { action: 'extract' }, (response) => {
        if (chrome.runtime.lastError) {
          console.warn('[BB:BG] content script not ready, injecting...', chrome.runtime.lastError.message);
          chrome.scripting.executeScript(
            { target: { tabId: msg.tabId }, files: ['content.js'] },
            () => {
              if (chrome.runtime.lastError) {
                console.error('[BB:BG] executeScript FAILED:', chrome.runtime.lastError.message);
                sendResponse({ error: '注入失败: ' + chrome.runtime.lastError.message });
                return;
              }
              console.log('[BB:BG] injected, retrying in 300ms...');
              setTimeout(() => {
                chrome.tabs.sendMessage(msg.tabId, { action: 'extract' }, (retryResp) => {
                  if (chrome.runtime.lastError) {
                    console.error('[BB:BG] retry FAILED:', chrome.runtime.lastError.message);
                    sendResponse({ error: '重试失败: ' + chrome.runtime.lastError.message });
                  } else {
                    console.log('[BB:BG] retry OK');
                    sendResponse(retryResp || { error: '提取失败(空)' });
                  }
                });
              }, 300);
            }
          );
          return;
        }
        console.log('[BB:BG] extract OK');
        sendResponse(response || { error: '提取失败(空)' });
      });
      return true;

    // ── content.js 代理: 跨域 fetch (避开 CORS, 携带 cookie) ──
    case 'fetchJSON':
      console.log('[BB:BG] fetchJSON', (msg.url || '').substring(0, 80));
      (async () => {
        const headers = {};
        if (msg.url.includes('bilibili.com')) {
          const cookie = await getBiliCookieHeader();
          if (cookie) headers['Cookie'] = cookie;
        }
        fetch(msg.url, { credentials: 'include', headers })
          .then(r => r.json())
          .then(data => sendResponse({ ok: true, data }))
          .catch(err => sendResponse({ ok: false, error: err.message }));
      })();
      return true;

    // ── B站 WBI 签名 fetch ──────────────────────────
    case 'fetchWbiJSON':
      (async () => {
        try {
          const url = msg.url;
          const u = new URL(url);
          const params = {};
          u.searchParams.forEach((v, k) => { params[k] = v; });
          const signed = await signWbi(params);
          if (!signed) { sendResponse({ ok: false, error: 'WBI sign failed' }); return; }
          const sp = new URLSearchParams();
          Object.entries(signed).forEach(([k,v]) => sp.append(k, v));
          const signedUrl = url.split('?')[0] + '?' + sp.toString();
          console.log('[BB:BG] fetchWbiJSON', signedUrl.substring(0, 100));
          const cookie = await getBiliCookieHeader();
          const headers = cookie ? { 'Cookie': cookie, 'Referer': 'https://www.bilibili.com/' } : { 'Referer': 'https://www.bilibili.com/' };
          console.log('[BB:BG] fetchWbiJSON cookie_len=', cookie.length, 'cookie_preview=', cookie.substring(0, 80));
          const resp = await fetch(signedUrl, { credentials: 'include', headers });
          const data = await resp.json();
          // DEBUG: 检查响应结构
          const hasDash = !!(data?.data?.dash);
          const dashAudioLen = data?.data?.dash?.audio?.length || 0;
          const subLen = data?.data?.subtitle?.subtitles?.length || 0;
          const code = data?.code;
          const loginMid = data?.data?.login_mid || 0;
          console.log('[BB:BG] WBI resp: code=', code, 'login_mid=', loginMid,
            'hasDash=', hasDash, 'dashAudio=', dashAudioLen, 'subs=', subLen);
          if (!hasDash && loginMid === 0) {
            console.log('[BB:BG] WARNING: login_mid=0, B站API未识别登录态');
          }
          sendResponse({ ok: true, data });
        } catch (err) {
          sendResponse({ ok: false, error: err.message });
        }
      })();
      return true;

    // ── WBI 签名 (仅签名, 不 fetch; content script 自己 fetch 以获取 cookie) ──
    case 'signWbiUrl':
      (async () => {
        try {
          const u = new URL(msg.url);
          const params = {};
          u.searchParams.forEach((v, k) => { params[k] = v; });
          const signed = await signWbi(params);
          if (!signed) { sendResponse({ ok: false, error: 'WBI sign failed' }); return; }
          const sp = new URLSearchParams();
          Object.entries(signed).forEach(([k,v]) => sp.append(k, v));
          const signedUrl = u.origin + u.pathname + '?' + sp.toString();
          sendResponse({ ok: true, signedUrl });
        } catch (err) {
          sendResponse({ ok: false, error: err.message });
        }
      })();
      return true;

    // ── 注入页面主世界执行 fetch (绕过 CSP, 使用 MAIN world) ──
    case 'executeInMainWorld':
      (async () => {
        const tabId = sender.tab?.id;
        if (!tabId) { sendResponse({ ok: false, error: 'no tabId' }); return; }
        try {
          await chrome.scripting.executeScript({
            target: { tabId },
            world: 'MAIN',
            func: (u, rid) => {
              fetch(u)
                .then(r => r.json())
                .then(data => {
                  document.dispatchEvent(new CustomEvent(rid + '_done', {
                    detail: (data && data.data) || {}
                  }));
                })
                .catch(err => {
                  console.debug('[BB:page] fetchFailed:', err.message);
                  document.dispatchEvent(new CustomEvent(rid + '_done', { detail: null }));
                });
            },
            args: [msg.url, msg.requestId],
          });
          sendResponse({ ok: true });
        } catch (err) {
          sendResponse({ ok: false, error: err.message });
        }
      })();
      return true;

    case 'callFlask':
      console.log('[BB:BG] callFlask', msg.endpoint);
      callFlaskAPI(msg.endpoint, msg.data)
        .then(data => {
          console.log('[BB:BG] Flask OK');
          sendResponse({ success: true, data });
        })
        .catch(err => {
          console.error('[BB:BG] Flask FAIL:', err.message);
          sendResponse({ success: false, error: err.message });
        });
      return true;

    default:
      console.warn('[BB:BG] unknown action:', msg.action);
      sendResponse({ error: '未知 action: ' + msg.action });
  }
});

// ─── Flask API ───────────────────────────────────────────
async function callFlaskAPI(endpoint, data) {
  const url = `${FLASK_URL}${endpoint}`;
  console.log('[BB:BG] fetch', url);
  const options = {
    method: data ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
  };
  if (data) {
    options.body = JSON.stringify(data);
  }
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Flask ${resp.status}: ${text}`);
  }
  return resp.json();
}

// ─── 健康检查 ────────────────────────────────────────────
setInterval(async () => {
  try {
    const resp = await fetch(`${FLASK_URL}/api/status`);
    chrome.action.setBadgeText({ text: resp.ok ? '' : '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#ea4335' });
  } catch (e) {
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#ea4335' });
  }
}, 10000);

// ─── B站 WBI 签名 (修复旧API返回错误字幕的Bug) ─────────
let _wbiKeys = null;  // {img_key, sub_key, mix_key}

async function getWbiKeys() {
  if (_wbiKeys) return _wbiKeys;
  try {
    const resp = await fetch('https://api.bilibili.com/x/web-interface/nav', { credentials: 'include' });
    const data = await resp.json();
    const wbiImg = data?.data?.wbi_img || {};
    const imgKey = (wbiImg.img_url || '').split('/').pop().split('.')[0];
    const subKey = (wbiImg.sub_url || '').split('/').pop().split('.')[0];
    _wbiKeys = {
      img_key: imgKey, sub_key: subKey,
      mix_key: imgKey.substring(0,16) + subKey.substring(0,16),
    };
    console.log('[BB:BG] WBI keys loaded');
    return _wbiKeys;
  } catch (e) {
    console.error('[BB:BG] WBI key fetch failed:', e.message);
    return null;
  }
}

function md5(str) {
  // 纯JS MD5实现
  function rotateLeft(n, s) { return (n << s) | (n >>> (32 - s)); }
  function addUnsigned(x, y) {
    var lsw = (x & 0xFFFF) + (y & 0xFFFF);
    var msw = (x >> 16) + (y >> 16) + (lsw >> 16);
    return (msw << 16) | (lsw & 0xFFFF);
  }
  function F(x,y,z) { return (x & y) | ((~x) & z); }
  function G(x,y,z) { return (x & z) | (y & (~z)); }
  function H(x,y,z) { return x ^ y ^ z; }
  function I(x,y,z) { return y ^ (x | (~z)); }
  function FF(a,b,c,d,x,s,ac) { a=addUnsigned(a,addUnsigned(addUnsigned(F(b,c,d),x),ac)); return addUnsigned(rotateLeft(a,s),b); }
  function GG(a,b,c,d,x,s,ac) { a=addUnsigned(a,addUnsigned(addUnsigned(G(b,c,d),x),ac)); return addUnsigned(rotateLeft(a,s),b); }
  function HH(a,b,c,d,x,s,ac) { a=addUnsigned(a,addUnsigned(addUnsigned(H(b,c,d),x),ac)); return addUnsigned(rotateLeft(a,s),b); }
  function II(a,b,c,d,x,s,ac) { a=addUnsigned(a,addUnsigned(addUnsigned(I(b,c,d),x),ac)); return addUnsigned(rotateLeft(a,s),b); }

  var x = [];
  var k, AA, BB, CC, DD, a, b, c, d;
  var S11=7, S12=12, S13=17, S14=22, S21=5, S22=9, S23=14, S24=20,
      S31=4, S32=11, S33=16, S34=23, S41=6, S42=10, S43=15, S44=21;

  str = unescape(encodeURIComponent(str));
  var len = str.length;
  for (k = 0; k < len; k++) x[k >> 2] |= (str.charCodeAt(k) & 0xff) << ((k % 4) << 3);
  x[len >> 2] |= 0x80 << ((len % 4) << 3);

  var N = ((len + 8) >> 6) + 1;
  for (k = len + 1; k < N * 16; k++) x[k >> 2] |= 0;
  x[N * 16 - 2] = len * 8;

  a = 0x67452301; b = 0xefcdab89; c = 0x98badcfe; d = 0x10325476;

  for (k = 0; k < N; k += 16) {
    AA = a; BB = b; CC = c; DD = d;
    a = FF(a,b,c,d, x[k+0], S11,0xd76aa478); d = FF(d,a,b,c, x[k+1], S12,0xe8c7b756); c = FF(c,d,a,b, x[k+2], S13,0x242070db); b = FF(b,c,d,a, x[k+3], S14,0xc1bdceee);
    a = FF(a,b,c,d, x[k+4], S11,0xf57c0faf); d = FF(d,a,b,c, x[k+5], S12,0x4787c62a); c = FF(c,d,a,b, x[k+6], S13,0xa8304613); b = FF(b,c,d,a, x[k+7], S14,0xfd469501);
    a = FF(a,b,c,d, x[k+8], S11,0x698098d8); d = FF(d,a,b,c, x[k+9], S12,0x8b44f7af); c = FF(c,d,a,b, x[k+10],S13,0xffff5bb1);b = FF(b,c,d,a, x[k+11],S14,0x895cd7be);
    a = FF(a,b,c,d, x[k+12],S11,0x6b901122);d = FF(d,a,b,c, x[k+13],S12,0xfd987193);c = FF(c,d,a,b, x[k+14],S13,0xa679438e);b = FF(b,c,d,a, x[k+15],S14,0x49b40821);
    a = GG(a,b,c,d, x[k+1], S21,0xf61e2562); d = GG(d,a,b,c, x[k+6], S22,0xc040b340); c = GG(c,d,a,b, x[k+11],S23,0x265e5a51);b = GG(b,c,d,a, x[k+0], S24,0xe9b6c7aa);
    a = GG(a,b,c,d, x[k+5], S21,0xd62f105d); d = GG(d,a,b,c, x[k+10],S22,0x2441453); c = GG(c,d,a,b, x[k+15],S23,0xd8a1e681);b = GG(b,c,d,a, x[k+4], S24,0xe7d3fbc8);
    a = GG(a,b,c,d, x[k+9], S21,0x21e1cde6); d = GG(d,a,b,c, x[k+14],S22,0xc33707d6); c = GG(c,d,a,b, x[k+3], S23,0xf4d50d87);b = GG(b,c,d,a, x[k+8], S24,0x455a14ed);
    a = GG(a,b,c,d, x[k+13],S21,0xa9e3e905);d = GG(d,a,b,c, x[k+2], S22,0xfcefa3f8); c = GG(c,d,a,b, x[k+7], S23,0x676f02d9);b = GG(b,c,d,a, x[k+12],S24,0x8d2a4c8a);
    a = HH(a,b,c,d, x[k+5], S31,0xfffa3942); d = HH(d,a,b,c, x[k+8], S32,0x8771f681); c = HH(c,d,a,b, x[k+11],S33,0x6d9d6122);b = HH(b,c,d,a, x[k+14],S34,0xfde5380c);
    a = HH(a,b,c,d, x[k+1], S31,0xa4beea44); d = HH(d,a,b,c, x[k+4], S32,0x4bdecfa9); c = HH(c,d,a,b, x[k+7], S33,0xf6bb4b60);b = HH(b,c,d,a, x[k+10],S34,0xbebfbc70);
    a = HH(a,b,c,d, x[k+13],S31,0x289b7ec6);d = HH(d,a,b,c, x[k+0], S32,0xeaa127fa);c = HH(c,d,a,b, x[k+3], S33,0xd4ef3085);b = HH(b,c,d,a, x[k+6], S34,0x4881d05);
    a = HH(a,b,c,d, x[k+9], S31,0xd9d4d039); d = HH(d,a,b,c, x[k+12],S32,0xe6db99e5);c = HH(c,d,a,b, x[k+15],S33,0x1fa27cf8);b = HH(b,c,d,a, x[k+2], S34,0xc4ac5665);
    a = II(a,b,c,d, x[k+0], S41,0xf4292244); d = II(d,a,b,c, x[k+7], S42,0x432aff97); c = II(c,d,a,b, x[k+14],S43,0xab9423a7);b = II(b,c,d,a, x[k+5], S44,0xfc93a039);
    a = II(a,b,c,d, x[k+12],S41,0x655b59c3);d = II(d,a,b,c, x[k+3], S42,0x8f0ccc92);c = II(c,d,a,b, x[k+10],S43,0xffeff47d);b = II(b,c,d,a, x[k+1], S44,0x85845dd1);
    a = II(a,b,c,d, x[k+8], S41,0x6fa87e4f); d = II(d,a,b,c, x[k+15],S42,0xfe2ce6e0);c = II(c,d,a,b, x[k+6], S43,0xa3014314);b = II(b,c,d,a, x[k+13],S44,0x4e0811a1);
    a = II(a,b,c,d, x[k+4], S41,0xf7537e82); d = II(d,a,b,c, x[k+11],S42,0xbd3af235);c = II(c,d,a,b, x[k+2], S43,0x2ad7d2bb);b = II(b,c,d,a, x[k+9], S44,0xeb86d391);
    a = addUnsigned(a, AA); b = addUnsigned(b, BB); c = addUnsigned(c, CC); d = addUnsigned(d, DD);
  }

  function wordToHex(w) {
    var hex = '';
    for (var i = 0; i < 4; i++) {
      var b = (w >>> (i * 8)) & 0xFF;
      hex += ('0' + b.toString(16)).slice(-2);
    }
    return hex;
  }
  return wordToHex(a) + wordToHex(b) + wordToHex(c) + wordToHex(d);
}

async function signWbi(params) {
  const keys = await getWbiKeys();
  if (!keys) return null;
  params.wts = Math.floor(Date.now() / 1000);
  const sorted = Object.keys(params).sort().map(k => k + '=' + encodeURIComponent(params[k])).join('&');
  params.w_rid = md5(sorted + keys.mix_key);
  return params;
}

console.log('[BB:BG] Started v2 (WBI+fetchJSON ready)');
