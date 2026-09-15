// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useEffect, useState } from 'react';
import { api, post } from './api';
const date = value => new Date(value * 1000).toLocaleString('zh-CN');
export function LoginSessions({ back, onAuthError }) {
  const [rows, setRows] = useState([]), [error, setError] = useState(''), [busy, setBusy] = useState(true);
  const [history, setHistory] = useState(null), [moreBusy, setMoreBusy] = useState(false), [tab, setTab] = useState('current');
  async function refresh() {
    setBusy(true);
    try { const [data, records] = await Promise.all([api('logins'), api('login-history')]); setRows(data.logins); setHistory(records); setError(''); }
    catch (e) { setError(e.message); if (e.status === 401) onAuthError(); }
    finally { setBusy(false); }
  }
  useEffect(() => { refresh(); }, []);
  async function more() {
    if (!history?.nextCursor || moreBusy || busy) return; setMoreBusy(true);
    try { const data = await api(`login-history?${new URLSearchParams({ cursor: history.nextCursor })}`); setHistory(old => ({ ...data, events: [...old.events, ...data.events] })); setError(''); }
    catch (e) { setError(e.message); if (e.status === 401) onAuthError(); }
    finally { setMoreBusy(false); }
  }
  async function revoke(row) { setBusy(true); try { const data = await post(`logins/${row.id}/revoke`, {}); if (data.current) { sessionStorage.clear(); onAuthError(); } else await refresh(); } catch (e) { setError(e.message); if (e.status === 401) onAuthError(); } finally { setBusy(false); } }
  return <section className="login-management"><button className="back" onClick={back}>‹ 返回会话</button><h1>登录管理</h1><p>管理网页登录，查看历史记录与失败尝试。</p>
    <nav className="login-tabs" aria-label="登录管理内容"><button aria-pressed={tab === 'current'} onClick={() => setTab('current')}>当前登录</button><button aria-pressed={tab === 'history'} onClick={() => setTab('history')}>登录记录</button></nav>
    {error ? <p className="alert" role="alert">{error}</p> : null}<button disabled={busy || moreBusy} onClick={refresh}>{busy ? '正在查询…' : '刷新登录记录'}</button>
    {tab === 'current' ? <><div className="login-cards">{rows.map(row => <article className="login-card" key={row.id}><h2>{row.label}{row.current ? <span className="new-badge">当前登录</span> : null}</h2><p>登录时间：{date(row.createdAt)}</p><p>最近操作：{date(row.lastActiveAt)}</p><p>最晚到期：{date(row.expiresAt)}</p><button className="outline" disabled={busy} onClick={() => revoke(row)}>{row.current ? '退出当前登录' : '退出这次登录'}</button></article>)}</div><p className="timeline-note">30 分钟无操作会失效，自动刷新不会延长登录。退出登录不会中断桌面已经执行的任务。</p></> : <section className="login-history">
      <h2>登录记录</h2>{history ? <><p className="history-summary">近 24 小时：成功 <strong>{history.summary.successful}</strong> 次 · 失败 <strong>{history.summary.failed}</strong> 次 · 拦截 <strong>{history.summary.blocked}</strong> 次</p><p className="timeline-note">按已保留记录统计，最新在前。发现不认识的成功登录，可到「当前登录」退出对应登录。</p>
      <ol className="login-event-list">{history.events.map(event => <li className={`login-event ${['login_rejected', 'login_throttled'].includes(event.kind) ? 'failed' : ''}`} key={event.id}><div className="login-event-heading"><strong>{event.title}</strong>{event.current ? <span className="new-badge">当前登录</span> : null}</div><time dateTime={new Date(event.at * 1000).toISOString()}>{date(event.at)}</time><p>相关设备与浏览器：{event.browser}</p>{event.kind === 'login_ok' ? <small>{event.sessionStatus === 'active' ? '此登录仍有效' : event.sessionStatus === 'ended' ? '此登录已退出或失效' : '旧记录未关联登录状态'}</small> : null}</li>)}</ol>
      {!history.events.length ? <p>暂无可归属到此账号的历史登录记录。</p> : null}{history.nextCursor ? <button className="more" disabled={moreBusy || busy} onClick={more}>{moreBusy ? '正在加载…' : '加载更早的登录记录'}</button> : <p className="timeline-note">已显示全部保留记录 · {history.retainedCount} 条</p>}</> : <p>{busy ? '正在读取历史记录…' : '记录暂时无法读取，请刷新。'}</p>}
      <p className="timeline-note">每个账号保留最近 1000 条记录，退出后仍保留。浏览器标识由客户端提供，仅供辨认，不能证明操作者身份。旧记录缺失的信息显示为未记录；无法关联账号的登录尝试不归入本账号记录。</p>
    </section>}
  </section>;
}
