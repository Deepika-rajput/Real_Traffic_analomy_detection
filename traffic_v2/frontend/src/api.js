// Thin client for the backend. Same-origin by default (nginx / vite proxy forward /api, /ws, /public).
const KEY = 'tm_api_key';
const OP = 'tm_operator';

export const BASE = (typeof window !== 'undefined' && window.__API_BASE__) || '';
const store = () => (typeof localStorage !== 'undefined' ? localStorage : { getItem: () => '', setItem() {} });

export const getKey = () => store().getItem(KEY) || '';
export const setKey = (k) => store().setItem(KEY, k || '');
export const getOperator = () => store().getItem(OP) || '';
export const setOperator = (o) => store().setItem(OP, o || '');

/** URL for <img>/<video>/<a> tags, which cannot send headers: the backend accepts ?key= */
export function url(path) {
  const k = getKey();
  return BASE + path + (k ? (path.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(k) : '');
}

export function wsUrl(path) {
  const k = getKey();
  const base = BASE ? BASE.replace(/^http/, 'ws') : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
  return base + path + (k ? '?key=' + encodeURIComponent(k) : '');
}

function headers(extra = {}) {
  const h = { ...extra };
  if (getKey()) h['X-API-Key'] = getKey();
  if (getOperator()) h['X-Operator'] = getOperator();
  return h;
}

async function errorMessage(res) {
  try {
    const j = await res.json();
    if (typeof j.detail === 'string') return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  } catch { /* not json */ }
  return `${res.status} ${res.statusText}`;
}

async function req(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: headers(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('tm-auth'));
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.status === 204 ? null : res.json();
}

export const api = {
  get: (p) => req('GET', p),
  post: (p, b) => req('POST', p, b === undefined ? {} : b),
  patch: (p, b) => req('PATCH', p, b),
  del: (p) => req('DELETE', p),
  /** multipart upload with progress (fetch cannot report upload progress) */
  upload(path, form, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', BASE + path);
      Object.entries(headers()).forEach(([k, v]) => x.setRequestHeader(k, v));
      x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
      x.onload = () => {
        let j = null;
        try { j = JSON.parse(x.responseText); } catch { /* ignore */ }
        if (x.status === 401) window.dispatchEvent(new Event('tm-auth'));
        if (x.status >= 200 && x.status < 300) return resolve(j);
        const d = j && j.detail;
        reject(new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((e) => e.msg).join('; ') : `${x.status} ${x.statusText}`));
      };
      x.onerror = () => reject(new Error('network error (is the backend running?)'));
      x.send(form);
    });
  },
};
