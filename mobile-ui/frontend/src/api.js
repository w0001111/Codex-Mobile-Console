// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
let csrf = '';
export function setCSRF(value) { csrf = value; }
export async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(`/api/${path}`, { ...options, signal: controller.signal, credentials: 'same-origin', headers: { ...(options.body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {}), ...options.headers } });
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || '暂时无法连接电脑'); error.status = response.status; throw error; }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('连接超时，请刷新核对；发送操作不会自动重试。');
    throw error;
  } finally { clearTimeout(timer); }
}
export function post(path, data) { return api(path, { method: 'POST', body: JSON.stringify(data) }); }
export function requestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
  const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// A slow history is one bounded server read. Poll its status, never restart it
// on every browser timeout. This helper is for read-only pages only.
export async function readPage(path, { alive = () => true, waiting = () => {}, timeout = 65000 } = {}) {
  const until = Date.now() + timeout;
  while (alive()) {
    const page = await api(path + (path.includes('?') ? '&' : '?') + 'async=1');
    if (!alive()) return null;
    if (page.error) throw new Error(page.error);
    if (!page.loading) return page;
    waiting(page.queued ? '正在排队读取历史…' : '正在读取历史消息…');
    if (Date.now() >= until) throw new Error('这段历史读取较慢，请稍后重试，或在电脑端检查该会话。');
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
  return null;
}
