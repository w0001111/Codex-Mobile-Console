// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React from 'react';
import { Quota } from './Quota';
import { ChevronRight, Search, RefreshCw, Pin } from 'lucide-react';
export function Status({ task }) { return <span className={`status ${task.status}`}><i />{task.statusLabel}</span>; }
export function TaskList({ data, busy, error, query, setQuery, filter, setFilter, group, setGroup, refresh, more, open, logout, logoutAll, manageLogins, onAuthError, onAbout }) {
  const summary = data.overview;
  return <section className="list-panel">
    <header className="top"><h1>会话</h1><span className={`connection ${error ? 'offline' : ''}`}><i />{error ? '连接待检查' : busy && !data.tasks.length ? '正在连接' : '电脑已连接'}</span></header>
    <Quota onAuthError={onAuthError}/>
    <nav className="overview" aria-label="会话状态概览">{[['active', '运行中'], ['needs_input', '等你处理'], ['new', '有新结果']].map(([key, label]) => <button key={key} aria-pressed={filter === key} className={`overview-card ${filter === key ? 'selected' : ''}`} onClick={() => setFilter(filter === key ? 'all' : key)}><strong>{summary ? summary[key] : '—'}</strong><span>{label}</span></button>)}</nav>
    <p className="coverage">{summary ? `${group === 'all' ? '全部项目' : '当前项目'} · 已检查 ${summary.checked}/${summary.total} 个会话 · ${summary.unknown} 个状态未知${summary.complete ? '' : ' · 目录尚未全部载入'}` : '正在读取会话目录…'}</p>
    <button className="current" onClick={() => data.current && open(data.current.number)} disabled={!data.current}>
      <span><small>当前会话</small><strong>{data.current?.title || '选择一个会话开始'}</strong></span>{data.current ? <span className="current-link">查看 <ChevronRight size={18}/></span> : null}
    </button>
    <label className="search"><Search size={20}/><input aria-label="搜索会话、简称或项目" placeholder="搜索会话、简称或项目" value={query} onChange={e => setQuery(e.target.value)}/></label>
    <div className="project-filter"><label htmlFor="project-group">你的项目分组</label><select id="project-group" value={group} onChange={e => setGroup(e.target.value)}><option value="all">全部项目</option>{(data.groups || []).map(g => <option key={g.id} value={g.id}>{g.pinned ? '★ ' : ''}{g.name}</option>)}</select></div>
    {data.groupSyncError ? <p className="alert">暂时未能同步桌面分组，请刷新重试。</p> : <p className="group-note">沿用 Codex 桌面的项目名称、归属和置顶顺序</p>}
    <div className="list-heading"><span>{filter === 'all' ? '全部会话' : { active: '运行中的会话', needs_input: '需要你处理', new: '有新结果' }[filter]}{data.matchingCount != null ? ` · ${data.matchingCount}` : ''}</span>{filter !== 'all' ? <button onClick={() => setFilter('all')}>查看全部</button> : <small>待处理优先</small>}</div>
    {error ? <p className="alert" role="alert">{error}</p> : null}
    <div className="rows" aria-busy={busy}>{data.tasks.map(t => <button className="task-row" key={t.number} onClick={() => open(t.number)}>
      <span className={`row-dot ${t.status}`}/><span className="row-copy"><strong>{t.pinned ? <Pin size={14} aria-label="已置顶"/> : null}{t.title}</strong><small>{t.project} · {t.ref}</small><small>{t.modelSettings?.model ? `${t.modelSettings.model} · ${t.modelSettings.effortLabel}` : '模型待查询'}</small><span>{t.feedback || '点开查看对话'}</span></span><span className="row-right">{t.newResult ? <span className="new-badge">新结果</span> : null}<span className={t.status}>{t.statusLabel}</span><ChevronRight size={18}/></span>
    </button>)}</div>
    {!data.tasks.length ? <p className="empty">{busy ? '正在读取会话…' : '当前范围内没有匹配会话'}</p> : null}
    {data.nextCursor ? <button className="more" disabled={busy} onClick={more}>{busy ? '正在加载…' : '加载更多会话'}</button> : null}
    <footer className="list-footer"><span>页面可见时自动更新</span><button disabled={busy} onClick={refresh}><RefreshCw size={17} className={busy ? 'spin' : ''}/>刷新</button></footer>
    <p className="list-note">未知状态不算已完成。新结果从网页首次检查后开始记录。</p>
    <div className="session-actions"><button onClick={onAbout}>关于本应用</button><button onClick={manageLogins}>登录管理</button><button onClick={logout}>退出登录</button><button onClick={logoutAll}>退出所有网页登录</button></div>
  </section>;
}
