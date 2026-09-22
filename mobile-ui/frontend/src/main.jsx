// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post, setCSRF } from './api';
import { TaskList } from './TaskList';
import { TaskDetail } from './TaskDetail';
import './style.css';
import { LoginSessions } from './LoginSessions';
import { Login } from './Login';
import { About } from './About';
import { BackToTop } from './BackToTop';
import { openViewSession, clearViewSession, saveNavigation, saveView } from './viewState';
import { useReadingPosition } from './useReadingPosition';
import { refreshListedTasks, STATUS_REFRESH_LIMIT } from './statusRefresh';
function App() {
  const [auth, setAuth] = useState(null), [data, setData] = useState({ tasks: [], current: null, groups: [], nextCursor: null }), [query, setQuery] = useState(''), [number, setNumber] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [group, setGroup] = useState('all'), [filter, setFilter] = useState('all'), [limit, setLimit] = useState(24);
  const [security, setSecurity] = useState(false), [about, setAbout] = useState(false);
  const serial = useRef(0), listReads = useRef(new Map()), listPanel = useRef(null);
  const listReading = useReadingPosition('list', listPanel, auth === true && !number && !security && !about, !busy, data);
  const [statusRefresh, setStatusRefresh] = useState(null);
  const refreshRun = useRef(0), refreshing = useRef(false), failedChecks = useRef(new Map());
  const [mode, setMode] = useState('web');
  const connected = useCallback(async () => { const r = await api('session'); const nav = await openViewSession(r.csrf); setQuery(typeof nav.query === 'string' ? nav.query : ''); setFilter(['all', 'active', 'needs_input', 'new'].includes(nav.filter) ? nav.filter : 'all'); setGroup(typeof nav.group === 'string' ? nav.group : 'all'); setLimit(Number.isInteger(nav.limit) ? Math.min(2000, Math.max(24, nav.limit)) : 24); setNumber(Number.isInteger(nav.number) && nav.number > 0 ? nav.number : null); setCSRF(r.csrf); setMode(r.mode || 'wechat'); setData(old => ({ ...old, current: r.current })); setBusy(true); setAuth(true); }, []);
  const loggedOut = useCallback(() => { serial.current++; refreshRun.current++; refreshing.current = false; failedChecks.current.clear(); clearViewSession(); setAuth(false); setCSRF(''); setData({ tasks: [], current: null, groups: [] }); setNumber(null); setSecurity(false); }, []);
  useEffect(() => { connected().catch(loggedOut); }, [connected, loggedOut]);
  const load = useCallback(async () => {
    const seq = ++serial.current; setBusy(true);
    const params = new URLSearchParams({ q: query, group, status: filter, limit, sort: 'message' });
    const key = params.toString();
    if (!listReads.current.has(key)) listReads.current.set(key, api(`tasks?${params}`).finally(() => listReads.current.delete(key)));
    try { const result = await listReads.current.get(key); if (seq !== serial.current) return; for (const task of result.tasks) { const failed = failedChecks.current.get(task.number); if (failed && (task.observedAt || 0) <= failed.checkedAt) { if (result.overview && task.status !== 'unknown') { result.overview.unknown++; if (task.status === 'active') result.overview.active--; if (['needs_input', 'error'].includes(task.status)) result.overview.needs_input--; } Object.assign(task, failed); } else failedChecks.current.delete(task.number); } listReading.preserve(); setData(result); setError(''); return result; }
    catch (e) { if (seq === serial.current) { setError(e.message); if (e.status === 401) loggedOut(); } }
    finally { if (seq === serial.current) setBusy(false); }
  }, [query, group, filter, limit, loggedOut, listReading.preserve]);
  useEffect(() => { refreshRun.current++; refreshing.current = false; failedChecks.current.clear(); setStatusRefresh(null); }, [auth, query, group, filter, limit]);
  useEffect(() => {
    if (!auth) return;
    const initial = setTimeout(load, 250), timer = setInterval(() => { if (!document.hidden && !refreshing.current) load(); }, 15000);
    return () => { clearTimeout(initial); clearInterval(timer); serial.current++; };
  }, [auth, load]);
  useEffect(() => {
    if (!auth) return;
    let last = 0;
    function activity(e) {
      if (!e.isTrusted || document.hidden || Date.now() - last < 60000) return;
      last = Date.now(); post('activity', {}).catch(e => { if (e.status === 401) loggedOut(); });
    }
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart'];
    events.forEach(name => window.addEventListener(name, activity, { passive: true }));
    return () => events.forEach(name => window.removeEventListener(name, activity));
  }, [auth, loggedOut]);
  useEffect(() => { if (auth) saveNavigation({ number, query, group, filter, limit }); }, [auth, number, query, group, filter, limit]);
  async function refreshStatus() {
    if (refreshing.current) return;
    const run = ++refreshRun.current;
    refreshing.current = true;
    const alive = () => refreshRun.current === run;
    setStatusRefresh({ loading: true, checked: 0, total: 0, unknown: 0 });
    try {
      const listing = await load();
      if (!alive()) return;
      if (!listing) { setStatusRefresh({ loading: false, error: '列表未能刷新，请稍后重试。' }); return; }
      setStatusRefresh({ loading: true, checked: 0, total: Math.min(STATUS_REFRESH_LIMIT, listing.tasks.length), unknown: 0 });
      const done = await refreshListedTasks(listing.tasks, {
        read: n => api(`tasks/${n}?view=summary`), alive,
        onProgress: setStatusRefresh,
        onResult: result => {
          if (result.refreshFailed) failedChecks.current.set(result.number, result); else failedChecks.current.delete(result.number);
          listReading.preserve();
          setData(old => ({ ...old, tasks: old.tasks.map(task => task.number === result.number ? { ...task, ...result } : task) }));
        },
      });
      if (!alive()) return;
      // Recompute the existing overview and filters from the newly observed cache.
      const updated = await load();
      if (alive()) setStatusRefresh({ ...done, error: updated ? '' : '状态检查已完成，但列表汇总未能更新，请稍后重试。' });
    } catch (e) {
      if (alive()) { refreshRun.current++; refreshing.current = false; setStatusRefresh({ loading: false, error: e.message }); if (e.status === 401) loggedOut(); }
    } finally { if (alive()) refreshing.current = false; }
  }
  function openTask(value) { if (!number) listReading.capture(); setNumber(value); }
  async function logout(all = false) { try { await post(all ? 'logout-all' : 'logout', {}); try { sessionStorage.clear(); } catch {} loggedOut(); } catch (e) { setError(e.message); } }
  function changeFilter(value) { saveView('list', { reading: null }); setFilter(value); setLimit(24); }
  function changeGroup(value) { saveView('list', { reading: null }); setGroup(value); setLimit(24); }
  if (about) return <About back={() => setAbout(false)}/>;
  if (auth === null) return <main className="login"><h1>Codex 控制台</h1><p>正在检查连接…</p></main>;
  if (!auth) return <Login done={connected} onAbout={() => setAbout(true)}/>;
  if (security) return <main className="security-workspace"><BackToTop/><LoginSessions back={() => setSecurity(false)} onAuthError={loggedOut}/></main>;
  return <main className={`workspace ${number ? 'has-detail' : ''}`}><BackToTop/><TaskList onAbout={() => { listReading.capture(); setAbout(true); }} panelRef={listPanel} onAuthError={loggedOut} manageLogins={() => { listReading.capture(); setSecurity(true); }} mode={mode} data={data} busy={busy} error={error} query={query} setQuery={v => { saveView('list', { reading: null }); setQuery(v); setLimit(24); }} filter={filter} setFilter={changeFilter} group={group} setGroup={changeGroup} statusRefresh={statusRefresh} refresh={refreshStatus} more={() => setLimit(v => Math.min(2000, v + 24))} open={openTask} logout={() => logout(false)} logoutAll={() => logout(true)}/>{number ? <TaskDetail mode={mode} key={number} number={number} back={() => { setNumber(null); load(); }} onChange={current => setData(old => ({ ...old, current }))} onPreferences={load} onAuthError={loggedOut}/> : <aside className="detail-placeholder"><span>选择一个会话</span><p>查看完整对话、执行反馈和新的结果。</p></aside>}</main>;
}
createRoot(document.getElementById('root')).render(<App/>);
