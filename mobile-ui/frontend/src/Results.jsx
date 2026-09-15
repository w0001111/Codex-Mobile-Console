// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useEffect, useRef, useState } from 'react';
import { readPage } from './api';
export function Results({ number, onAuthError }) {
  const [page, setPage] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const mounted = useRef(true), reading = useRef(false);
  useEffect(() => () => { mounted.current = false; }, []);
  const files = page?.files || [], cursor = page?.nextCursor;
  async function load(older = false) {
    if (reading.current) return; reading.current = true; setBusy(true); setError('');
    try {
      const path = `tasks/${number}/files${older && cursor ? '?' + new URLSearchParams({ cursor }) : ''}`;
      const data = await readPage(path, { alive: () => mounted.current });
      if (data && mounted.current) setPage(old => ({ ...data, skippedFiles: (older ? old?.skippedFiles || 0 : 0) + (data.skippedFiles || 0) }));
    } catch (e) { if (mounted.current) { setError(e.message); if (e.status === 401) onAuthError(); } }
    finally { reading.current = false; if (mounted.current) setBusy(false); }
  }
  return <details className="results disclosure" onToggle={e => { if (e.currentTarget.open && !page && !reading.current) load(); }}><summary>成果文件 <small>{files.length} 个</small><span className="expand-hint">点击展开 / 收起</span></summary><div className="disclosure-content"><p className="timeline-note">仅收录本任务明确输出的文件，下载的是收录时版本。普通引用、输入附件和工作目录之外的文件请在桌面查看。</p>{files.map(f => <article className="file-card" key={f.id}>{f.image ? <img loading="lazy" alt={f.name} src={`/api/tasks/${number}/files/${f.id}/preview`}/> : null}<div><strong>{f.name}</strong><small>{f.size < 1024 ? `${f.size} B` : `${(f.size / 1024 / 1024).toFixed(2)} MB`} · {new Date(f.capturedAt * 1000).toLocaleDateString('zh-CN')} 收录</small></div><a className="outline" href={`/api/tasks/${number}/files/${f.id}`} download>下载</a></article>)}{!files.length ? <p>{busy ? '正在整理成果文件，不影响查看对话。' : !page ? '展开后检查本任务的成果文件。' : '已检查的对话中暂无可下载成果。'}</p> : null}{page?.skippedFiles ? <p className="timeline-note">部分成果因文件范围、类型、大小或读取限制未收录，请在桌面查看。</p> : null}{error ? <p className="alert">{error}<button disabled={busy} onClick={() => load(!!cursor)}>重试</button></p> : null}{cursor ? <button className="more" disabled={busy} onClick={() => load(true)}>{busy ? '正在查找…' : '查找更早的成果'}</button> : <small>{!page ? '成果检查尚未完成' : '已检查到会话开始'}</small>}</div></details>;
}
export function Receipts({ rows }) {
  if (!rows.length) return null;
  return <details className="receipts disclosure"><summary>消息送达记录 <small>{rows.length} 条</small><span className="expand-hint">点击展开 / 收起</span></summary><div className="disclosure-content">{rows.map(row => <div className={`receipt ${row.phase}`} key={row.requestId}><strong>{row.label}</strong><small>{new Date(row.createdAt * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 编号 {row.requestId.slice(0, 8)}</small>{row.hint ? <p>{row.hint}</p> : null}</div>)}</div></details>;
}
