// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React from 'react';
import { Quota } from './Quota';
import { ChevronRight, Search, RefreshCw, Pin } from 'lucide-react';
function stateLabel(task) { return task.status === 'idle' && task.statusLabel === '已完成' ? '本轮结束' : task.statusLabel; }
function messageLabel(task) { return task.messageAt ? `${new Date(task.messageAt * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ${task.messageKind === 'sent' ? '发送' : '回复'}` : '消息时间未知'; }
function timeLabel(at) { return at ? new Date(at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''; }
export function Status({ task }) { return <span className={`status ${task.status}`}><i />{stateLabel(task)}</span>; }
export function TaskList({ panelRef, data, busy, error, query, setQuery, filter, setFilter, group, setGroup, statusRefresh, refresh, more, open, logout, logoutAll, manageLogins, onAuthError, onAbout }) {
  const summary = data.overview;
  const checking = !!statusRefresh?.loading;
  return <section ref={panelRef} className="list-panel">
    <header className="top home-top"><h1>会话</h1><div className="home-actions"><span className={`connection ${error ? 'offline' : ''}`}><i />{error ? '连接待检查' : busy && !data.tasks.length ? '正在连接' : '列表已连接'}</span><button className="refresh-status" disabled={busy || checking} onClick={refresh}><RefreshCw size={17} className={checking ? 'spin' : ''}/>{checking ? '刷新中…' : '刷新状态'}</button></div></header>
    <p className={`status-refresh-note ${statusRefresh?.error ? 'error' : ''}`} role="status">{statusRefresh?.error || (checking ? statusRefresh.total ? `正在检查列表前 8 项：${statusRefresh.checked}/${statusRefresh.total} 个任务` : '正在读取当前列表…' : statusRefresh?.at ? `${new Date(statusRefresh.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 检查了 ${statusRefresh.total} 个任务 · ${statusRefresh.unknown} 个实时状态未知${statusRefresh.failed ? `（${statusRefresh.failed} 个查询失败）` : ''}` : '刷新状态只检查当前列表前 8 个任务。')}</p>
    <Quota onAuthError={onAuthError}/>
    <nav className="overview" aria-label="会话状态概览">{[['active', '运行中'], ['needs_input', '等你处理'], ['new', '有新结果']].map(([key, label]) => <button key={key} aria-pressed={filter === key} className={`overview-card ${filter === key ? 'selected' : ''}`} onClick={() => setFilter(filter === key ? 'all' : key)}><strong>{summary ? summary[key] : '—'}</strong><span>{label}</span></button>)}</nav>
    <p className="coverage">{summary ? `${group === 'all' ? '全部项目' : '当前项目'} · 已检查 ${summary.checked}/${summary.total} 个会话 · ${summary.unknown} 个状态未知${summary.complete ? '' : ' · 目录尚未全部载入'}` : '正在读取会话目录…'}</p>
    <button className="current" onClick={() => data.current && open(data.current.number)} disabled={!data.current}>
      <span><small>当前会话</small><strong>{data.current?.title || '选择一个会话开始'}</strong></span>{data.current ? <span className="current-link">查看 <ChevronRight size={18}/></span> : null}
    </button>
    <label className="search"><Search size={20}/><input aria-label="搜索会话、简称或项目" placeholder="搜索会话、简称或项目" value={query} onChange={e => setQuery(e.target.value)}/></label>
    <div className="project-filter"><label htmlFor="project-group">你的项目分组</label><select id="project-group" value={group} onChange={e => setGroup(e.target.value)}><option value="all">全部项目</option>{(data.groups || []).map(g => <option key={g.id} value={g.id}>{g.pinned ? '★ ' : ''}{g.name}</option>)}</select></div>
    {data.groupSyncError ? <p className="alert">暂时未能同步桌面分组，请刷新重试。</p> : <p className="group-note">沿用 Codex 桌面的项目名称、归属和置顶顺序</p>}
    <div className="list-heading"><span>{filter === 'all' ? '全部会话' : { active: '运行中的会话', needs_input: '需要你处理', new: '有新结果' }[filter]}{data.matchingCount != null ? ` · ${data.matchingCount}` : ''}</span>{filter !== 'all' ? <button onClick={() => setFilter('all')}>查看全部</button> : <small>最近发送 / 回复</small>}</div>
    {error ? <p className="alert" role="alert">{error}</p> : null}
    <div className="rows" aria-busy={busy}>{data.tasks.map(t => <button className="task-row" data-read-key={`task-${t.number}`} key={t.number} onClick={() => open(t.number)}>
      <span className={`row-dot ${t.status}`}/><span className="row-copy"><strong>{t.pinned ? <Pin size={14} aria-label="已收藏"/> : null}{t.title}</strong><small>{t.project} · {t.ref}</small><small className="message-time">{messageLabel(t)}</small><small>{t.modelSettings?.model ? `${t.modelSettings.model} · ${t.modelSettings.effortLabel}` : '模型待查询'}</small><span>{t.feedback || '点开查看对话'}</span></span><span className="row-right">{t.newResult ? <span className="new-badge">新结果</span> : null}<span className="row-state"><span className={t.status}>{stateLabel(t)}</span><small>{t.refreshFailed ? '查询失败' : t.observedAt ? `${timeLabel(t.observedAt)} 查询` : '尚未查询'}</small></span><ChevronRight size={18}/></span>
    </button>)}</div>
    {!data.tasks.length ? <p className="empty">{busy ? '正在读取会话…' : '当前范围内没有匹配会话'}</p> : null}
    {data.nextCursor ? <button className="more" disabled={busy} onClick={more}>{busy ? '正在加载…' : '加载更多会话'}</button> : null}
    <footer className="list-footer"><span>页面可见时自动更新</span><button disabled={busy || checking} onClick={refresh}><RefreshCw size={17} className={checking ? 'spin' : ''}/>{checking ? '刷新中…' : '刷新状态'}</button></footer>
    <p className="list-note">未知状态不算已完成。新结果从网页首次检查后开始记录。</p>
    <div className="session-actions"><button onClick={onAbout}>关于本应用</button><button onClick={manageLogins}>登录管理</button><button onClick={logout}>退出登录</button><button onClick={logoutAll}>退出所有网页登录</button></div>
  </section>;
}
