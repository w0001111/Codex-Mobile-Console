// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, RefreshCw, Info, Pin, Pencil } from 'lucide-react';
import { api, post, requestId, readPage } from './api';
import { ModelSettings } from './ModelSettings';
import { Results, Receipts } from './Results';
import { Status } from './TaskList';
function dateLabel(ms) { return ms ? new Date(ms).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '时间未记录'; }
function mergeTurns(older, newer) { const map = new Map(older.map(t => [t.id, t])); newer.forEach(t => map.set(t.id, t)); return [...map.values()].sort((a, b) => a.at - b.at); }
function Message({ item, initiallyExpanded = false }) {
  const [expanded, setExpanded] = useState(initiallyExpanded), long = item.text.length > 1800;
  return <article className={`timeline-message ${item.role}`}><span className="message-role">{{ user: '你', feedback: '执行反馈', result: '最终回复', operation: '执行记录' }[item.role]}</span><div className="copy">{long && !expanded ? item.text.slice(0, 1800) + '…' : item.text}</div>{long ? <button className="expand-message" onClick={() => setExpanded(v => !v)}>{expanded ? '收起' : `展开完整内容（${item.text.length.toLocaleString()} 字符）`}</button> : null}</article>;
}
function TurnMessages({ items }) {
  const blocks = [];
  for (const item of items) {
    if (item.role === 'operation' || item.role === 'feedback') {
      const last = blocks[blocks.length - 1];
      if (last?.execution) last.items.push(item); else blocks.push({ id: item.id, execution: true, items: [item] });
    } else blocks.push({ id: item.id, execution: false, items: [item] });
  }
  return blocks.map(block => block.execution ? <details className="execution-records disclosure" key={block.id}><summary>执行记录与反馈 <small>{block.items.length} 条</small><span className="expand-hint">点击展开 / 收起</span></summary><div className="disclosure-content">{block.items.map(item => <Message key={item.id} item={item}/>)}</div></details> : <Message key={block.id} item={block.items[0]}/>);
}
export function TaskDetail({ number, back, onChange, onPreferences, onAuthError }) {
  const [task, setTask] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [draft, setDraft] = useState(''), [pending, setPending] = useState(null), [working, setWorking] = useState(false);
  const [history, setHistory] = useState([]), [cursor, setCursor] = useState(null), [historyError, setHistoryError] = useState(''), [loadingOlder, setLoadingOlder] = useState(false);
  const [editing, setEditing] = useState(false), [alias, setAlias] = useState('');
  const [receipts, setReceipts] = useState([]);
  const pendingRef = useRef(null), historyLoading = useRef(false);
  const [historyStage, setHistoryStage] = useState('正在读取历史消息…');
  const loading = useRef(false), mounted = useRef(true), historyReady = useRef(false), knownTurns = useRef(new Set());
  useEffect(() => { window.scrollTo(0, 0); mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function loadHistory() {
    if (historyLoading.current) return; historyLoading.current = true; setHistoryStage('正在读取历史消息…');
    try {
      const page = await readPage(`tasks/${number}/history`, { alive: () => mounted.current, waiting: setHistoryStage });
      if (!page || !mounted.current) return;
      setHistoryError(''); const overlap = page.turns.some(t => knownTurns.current.has(t.id));
      if (!historyReady.current || (!overlap && page.turns.length)) {
        setHistory(page.turns); setCursor(page.nextCursor); knownTurns.current = new Set(page.turns.map(t => t.id)); historyReady.current = true;
      } else { setHistory(old => mergeTurns(old, page.turns)); page.turns.forEach(t => knownTurns.current.add(t.id)); }
    } catch (e) { if (mounted.current) { setHistoryError(e.message); if (e.status === 401) onAuthError(); } }
    finally { historyLoading.current = false; if (mounted.current) setHistoryStage(''); }
  }
  async function refresh() {
    loadHistory();
    if (loading.current) return; loading.current = true; setBusy(true);
    try {
      const data = await api(`tasks/${number}?view=summary`); if (!mounted.current) return;
      setTask(data); let rows = data.deliveries || []; const p = pendingRef.current;
      // Display metadata immediately; exact delivery checks cannot delay history.
      setError(''); reconcile(rows);
      if (p && !rows.some(r => r.requestId === p.requestId)) { const exact = await api(`tasks/${number}/deliveries?${new URLSearchParams({ requestId: p.requestId })}`); if (!mounted.current) return; reconcile([...exact.deliveries, ...rows]); }
    } catch (e) { if (mounted.current) { setError(e.message); if (e.status === 401) onAuthError(); } }
    finally { loading.current = false; if (mounted.current) setBusy(false); }
  }
  useEffect(() => {
    const saved = sessionStorage.getItem(`pending-${number}`); if (saved) { try { const p = JSON.parse(saved); setPending(p); pendingRef.current = p; setDraft(p.text); setNotice('上次发送尚未核对。请先查看对话，确认后再开始新消息。'); } catch {} }
    refresh(); const timer = setInterval(() => { if (!document.hidden) refresh(); }, 8000); return () => clearInterval(timer);
  }, [number]);
  function reconcile(rows) {
    const p = pendingRef.current;
    if (p) {
      const found = rows.find(r => r.requestId === p.requestId);
      if (found && !['sending', 'uncertain'].includes(found.phase)) { setPending(null); pendingRef.current = null; sessionStorage.removeItem(`pending-${number}`); if (found.phase !== 'refused') setDraft(''); }
      if (!found) rows = [{ requestId: p.requestId, phase: 'uncertain', label: '结果待核对', createdAt: p.createdAt || Date.now() / 1000, hint: '尚未取得这条消息的回执，请勿重复发送。' }, ...rows];
    }
    setReceipts(rows);
  }
  async function older() {
    if (!cursor || loadingOlder) return; setLoadingOlder(true);
    try { const page = await readPage(`tasks/${number}/history?${new URLSearchParams({ cursor })}`, { alive: () => mounted.current }); if (!page || !mounted.current) return; setHistory(old => mergeTurns(page.turns, old)); page.turns.forEach(t => knownTurns.current.add(t.id)); setCursor(page.nextCursor); setHistoryError(''); }
    catch (e) { if (mounted.current) { setHistoryError(e.message); if (e.status === 401) onAuthError(); } }
    finally { if (mounted.current) setLoadingOlder(false); }
  }
  async function preference(kind, value) {
    if (working) return; setWorking(true);
    try { await post(`tasks/${number}/preference`, { kind, value }); if (!mounted.current) return; setEditing(false); setNotice(kind === 'seen' ? '已标记为已读。' : kind === 'pin' ? (value ? '已在网页置顶。' : '已取消网页置顶。') : '网页简称已保存。'); await refresh(); onPreferences(); }
    catch (e) { if (mounted.current) { setNotice(e.message); if (e.status === 401) onAuthError(); } }
    finally { if (mounted.current) setWorking(false); }
  }
  async function action(kind) {
    if (working) return; setWorking(true); setNotice('');
    const payload = { action: kind, number, requestId: requestId(), text: draft, createdAt: Date.now() / 1000 };
    if (kind === 'send') { setPending(payload); pendingRef.current = payload; setReceipts(old => [{ requestId: payload.requestId, phase: 'sending', label: '正在发送', createdAt: payload.createdAt }, ...old].slice(0, 8)); sessionStorage.setItem(`pending-${number}`, JSON.stringify(payload)); }
    try {
      const result = await post('action', payload); if (!mounted.current) return; setNotice(result.response); onChange(result.current);
      if (kind === 'send' && result.delivery !== 'uncertain') { setPending(null); pendingRef.current = null; sessionStorage.removeItem(`pending-${number}`); if (result.delivery === 'accepted') setDraft(''); }
      await refresh();
    } catch (e) { if (mounted.current) { if (kind === 'send') setReceipts(old => old.map(r => r.requestId === payload.requestId ? { ...r, phase: 'uncertain', label: '结果待核对', hint: '网络中断，正在核对回执，请勿重复发送。' } : r)); setNotice(kind === 'send' ? '网络中断，发送结果待核对。请先查看对话，避免重复执行。' : e.message); if (e.status === 401) onAuthError(); } }
    finally { if (mounted.current) setWorking(false); }
  }
  function resolved() { setPending(null); pendingRef.current = null; sessionStorage.removeItem(`pending-${number}`); setDraft(''); setNotice('已清空本地待核对标记，可以编辑新消息。'); }
  const finalTurn = [...history].reverse().find(turn => turn.status === 'completed' && turn.items.some(item => item.role === 'result'));
  const latestTurn = history[history.length - 1];
  const hasNewerTurn = finalTurn && latestTurn?.id !== finalTurn.id;
  return <section className="detail-panel"><button className="back" onClick={back}><ChevronLeft size={23}/>会话</button>
    <div className="connection-controls"><button className="primary" disabled={working || !!task?.live} onClick={() => action('select')}>{working ? '正在处理…' : task?.live ? '桌面已连接' : '连接桌面会话'}</button><button disabled={busy} onClick={refresh}><RefreshCw size={16} className={busy ? 'spin' : ''}/>刷新</button></div>
    {!task ? <div className="empty">{error || '正在读取会话…'}{notice ? <p role="status">{notice}</p> : null}</div> : <>
      <div className="detail-body"><h1>{task.title}</h1>{task.alias ? <p className="original-title">原名：{task.originalTitle}</p> : null}<p className="project">项目：{task.project} · {task.ref}</p>
        <div className="status-line"><Status task={task}/><span>{dateLabel(task.observedAt * 1000)} 更新</span></div>{!task.live ? <p className="timeline-note">历史消息可独立查看。需要继续任务时，点顶部“连接桌面会话”，再刷新状态；也可以先在电脑端打开这段会话。</p> : null}
        <ModelSettings number={number} settings={task.modelSettings} canChange={task.canSend && !error} working={working} status={task.status} onBusyChange={setWorking} refresh={refresh} onAuthError={onAuthError}/>
        <section className="latest-reply"><div className="latest-reply-heading"><h2>{hasNewerTurn ? '上一轮最终回复' : '最新最终回复'}</h2>{finalTurn ? <small>{dateLabel(finalTurn.at)}</small> : null}</div>
          {hasNewerTurn ? <p className="timeline-note">后面还有新的轮次，请以上方状态判断当前进度。</p> : null}
          {finalTurn ? finalTurn.items.filter(item => item.role === 'result').map(item => <Message key={finalTurn.id + ':' + item.id} item={item} initiallyExpanded/>) : <p className="timeline-note">{historyError ? historyError : !historyReady.current && historyStage ? historyStage : task.status === 'active' ? '本轮仍在执行，尚未读取到最终回复。' : '已加载的对话中暂无最终回复。'}{cursor ? ' 可展开下方对话时间线，加载更早的回复。' : ''}</p>}
        </section>
        {task.live && task.current?.number !== number ? <button className="outline" disabled={working} onClick={() => action('select')}>设为当前会话</button> : null}
        <div className="organize-actions"><button disabled={working} aria-pressed={task.pinned} onClick={() => preference('pin', !task.pinned)}><Pin size={16}/>{task.pinned ? '取消网页置顶' : '网页置顶'}</button><button onClick={() => { setAlias(task.alias || ''); setEditing(v => !v); }}><Pencil size={15}/>设置简称</button></div>
        {editing ? <form className="alias-form" onSubmit={e => { e.preventDefault(); preference('alias', alias); }}><label htmlFor="alias">网页简称（留空恢复原名）</label><div><input id="alias" maxLength={30} value={alias} onChange={e => setAlias(e.target.value)}/><button disabled={working} className="primary">保存</button></div></form> : null}
        {error ? <p className="alert" role="alert">{error}；下方显示的是上次查询结果。</p> : null}{notice ? <p className="notice" role="status">{notice}</p> : null}
        {task.newResult ? <div className="unread-notice"><strong>有新结果</strong><button disabled={working} onClick={() => preference('seen', task.resultRevision)}>标为已读</button></div> : null}
        {task.status === 'needs_input' ? <p className="alert">这个会话正在等待你处理，请在 Codex 桌面查看具体确认内容。</p> : task.status === 'error' ? <p className="alert">本轮执行出错，请查看对话并在桌面检查。</p> : null}
        <Receipts rows={receipts}/><Results number={number} onAuthError={onAuthError}/><details className="conversation-history disclosure"><summary>对话时间线<span className="expand-hint">点击展开 / 收起</span></summary><div className="disclosure-content"><p className="timeline-note">{task.live ? '桌面实时更新' : '已保存的历史 · 实时状态未知'}</p>
        {historyError ? <p className="alert" role="alert">{historyError}<button onClick={refresh}>重试</button></p> : null}
        <div className="timeline">{[...history].reverse().map(turn => <section className="timeline-turn" key={turn.id}><div className="turn-time">{dateLabel(turn.at)} · {{ completed: '本轮结束', inProgress: '进行中', failed: '执行失败', interrupted: '已中断' }[turn.status] || '历史记录'}{turn.executionSettings ? ` · ${turn.executionSettings.model} · ${turn.executionSettings.effortLabel}` : ''}</div><TurnMessages items={turn.items}/></section>)}</div>
        {cursor ? <button className="more" disabled={loadingOlder} onClick={older}>{loadingOlder ? '正在加载历史…' : '加载更早的对话'}</button> : historyReady.current && history.length ? <p className="history-start">已到这段会话的开始</p> : null}
        {!history.length && !historyError ? <p className="empty">{historyStage || '还没有可展示的对话消息。'}</p> : null}<p className="timeline-note">最新轮次在前，每轮内部按消息发生顺序展示。图片附件和工具原始输出请在桌面查看。</p></div></details>
        {task.current?.number === number ? <button className="leave" disabled={working} onClick={() => action('leave')}>取消当前会话选择</button> : null}
      </div>
      <div className="composer">{receipts.length ? <div className={`composer-receipt ${receipts[0].phase}`} role="status"><strong>{receipts[0].label}</strong><span>消息 {receipts[0].requestId.slice(0, 8)}</span></div> : null}<label className="sr-only" htmlFor="message">给这个会话发消息</label><textarea id="message" maxLength={4000} placeholder="给这个会话发消息…" value={draft} disabled={working || !!pending} onChange={e => setDraft(e.target.value)}/><div className="composer-bottom"><span><Info size={15}/>{pending ? (working ? '正在发送，请稍候' : '发送结果待核对') : error ? '连接异常，暂不能发送' : task.canSend ? `发送到 ${task.ref} · ${task.title.length > 36 ? task.title.slice(0, 36) + '…' : task.title}` : task.status === 'active' ? '运行中暂不能发送' : task.status === 'needs_input' ? '请先在桌面完成确认' : '请先连接会话并刷新状态'}</span><button className="primary" disabled={!!error || !task.canSend || !draft.trim() || working || !!pending} onClick={() => action('send')}>{working ? '处理中' : '发送'}</button></div>{pending ? <button className="resolve" disabled={working} onClick={resolved}>已核对会话，开始新消息</button> : null}</div>
    </>}
  </section>;
}
