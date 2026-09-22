// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
// Tab-local UI state only. A new authenticated session cannot inherit another
// session's drafts. Only unsent drafts and reading/navigation state are stored;
// credentials and loaded conversation messages are not cached here.
const KEY = 'codex-view-v1';
let state = { scope: '', views: {}, navigation: {} };
let enabled = false;

export async function openViewSession(csrf) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(csrf));
  const scope = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, '0')).join('');
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(KEY)); } catch {}
  state = saved?.scope === scope && saved.views && saved.navigation ? saved : { scope, views: {}, navigation: {} };
  enabled = true;
  persist();
  return state.navigation;
}
function persist() {
  if (!enabled) return false;
  try { sessionStorage.setItem(KEY, JSON.stringify(state)); return true; } catch { return false; }
}
export function clearViewSession() {
  enabled = false;
  state = { scope: '', views: {}, navigation: {} };
  try { sessionStorage.removeItem(KEY); } catch {}
}
export function getView(key) { return state.views[key] || {}; }
export function saveView(key, patch) {
  if (!enabled) return false;
  state.views[key] = { ...getView(key), ...patch };
  return persist();
}
export function saveNavigation(value) { if (enabled) { state.navigation = value; persist(); } }
