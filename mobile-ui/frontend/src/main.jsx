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
function App() {
  const [auth, setAuth] = useState(null), [data, setData] = useState({ tasks: [], current: null, groups: [], nextCursor: null }), [query, setQuery] = useState(''), [number, setNumber] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [group, setGroup] = useState('all'), [filter, setFilter] = useState('all'), [limit, setLimit] = useState(24);
  const serial = useRef(0), listReads = useRef(new Map());
  const [security, setSecurity] = useState(false);
  const [about, setAbout] = useState(false);
  const [mode, setMode] = useState('web');
  const connected = useCallback(async () => { const r = await api('session'); setCSRF(r.csrf); setMode(r.mode || 'wechat'); setData(old => ({ ...old, current: r.current })); setBusy(true); setAuth(true); }, []);
  const loggedOut = useCallback(() => { serial.current++; setAuth(false); setCSRF(''); setData({ tasks: [], current: null, groups: [] }); setNumber(null); setSecurity(false); }, []);
  useEffect(() => { connected().catch(loggedOut); }, [connected, loggedOut]);
  const load = useCallback(async () => {
    const seq = ++serial.current; setBusy(true);
    const params = new URLSearchParams({ q: query, group, status: filter, limit });
    const key = params.toString();
    if (!listReads.current.has(key)) listReads.current.set(key, api(`tasks?${params}`).finally(() => listReads.current.delete(key)));
    try { const result = await listReads.current.get(key); if (seq !== serial.current) return; setData(result); setError(''); }
    catch (e) { if (seq === serial.current) { setError(e.message); if (e.status === 401) loggedOut(); } }
    finally { if (seq === serial.current) setBusy(false); }
  }, [query, group, filter, limit, loggedOut]);
  useEffect(() => {
    if (!auth) return;
    const initial = setTimeout(load, 250), timer = setInterval(() => { if (!document.hidden) load(); }, 15000);
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
  async function logout(all = false) { try { await post(all ? 'logout-all' : 'logout', {}); sessionStorage.clear(); loggedOut(); } catch (e) { setError(e.message); } }
  function changeFilter(value) { setFilter(value); setLimit(24); }
  function changeGroup(value) { setGroup(value); setLimit(24); }
  if (about) return <About back={() => setAbout(false)}/>;
  if (auth === null) return <main className="login"><h1>Codex 控制台</h1><p>正在检查连接…</p></main>;
  if (!auth) return <Login done={connected} onAbout={() => setAbout(true)}/>;
  if (security) return <main className="security-workspace"><LoginSessions back={() => setSecurity(false)} onAuthError={loggedOut}/></main>;
  return <main className={`workspace ${number ? 'has-detail' : ''}`}><TaskList onAbout={() => setAbout(true)} onAuthError={loggedOut} manageLogins={() => setSecurity(true)} mode={mode} data={data} busy={busy} error={error} query={query} setQuery={v => { setQuery(v); setLimit(24); }} filter={filter} setFilter={changeFilter} group={group} setGroup={changeGroup} refresh={load} more={() => setLimit(v => Math.min(2000, v + 24))} open={setNumber} logout={() => logout(false)} logoutAll={() => logout(true)}/>{number ? <TaskDetail mode={mode} key={number} number={number} back={() => { setNumber(null); load(); }} onChange={current => setData(old => ({ ...old, current }))} onPreferences={load} onAuthError={loggedOut}/> : <aside className="detail-placeholder"><span>选择一个会话</span><p>查看完整对话、执行反馈和新的结果。</p></aside>}</main>;
}
createRoot(document.getElementById('root')).render(<App/>);
