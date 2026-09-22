// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useEffect, useRef, useState } from 'react';
import { readPage, requestId } from './api';
import { ArtifactImage } from './ArtifactImage';
export function Results({ number, onAuthError, initialOpen = false, onOpenChange = () => {}, refreshKey = 0, revision = '', autoLoad = false, onFiles = () => {} }) {
  const [open, setOpen] = useState(initialOpen);
  const [page, setPage] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const mounted = useRef(true), reading = useRef(false), expanded = useRef(initialOpen), rerun = useRef(false), failedOlder = useRef(false);
  const notify = useRef(onFiles); notify.current = onFiles;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const files = page?.files || [], cursor = page?.nextCursor;
  async function load(older = false) {
    if (reading.current) { if (!older) rerun.current = true; return; }
    reading.current = true; setBusy(true); setError(''); failedOlder.current = older;
    try {
      const query = new URLSearchParams({ refresh: requestId() });
      if (older && cursor) query.set('cursor', cursor);
      const data = await readPage(`tasks/${number}/files?${query}`, { alive: () => mounted.current });
      if (data && mounted.current) {
        setPage(old => ({ ...data, skippedFiles: (older ? old?.skippedFiles || 0 : 0) + (data.skippedFiles || 0) }));
        notify.current(data.files || []);
      }
    } catch (e) { if (mounted.current) { setError(e.message); if (e.status === 401) onAuthError(); } }
    finally {
      reading.current = false;
      if (mounted.current) { setBusy(false); if (rerun.current) { rerun.current = false; load(); } }
    }
  }
  useEffect(() => { if (expanded.current || autoLoad) load(); }, [refreshKey, revision, autoLoad]);
  return <details className="results disclosure" data-read-key="results" open={open} onToggle={e => { expanded.current = e.currentTarget.open; setOpen(expanded.current); onOpenChange(expanded.current); if (expanded.current) load(); }}>
    <summary>成果文件 <small>{files.length} 个</small><span className="expand-hint">点击展开 / 收起</span></summary>
    <div className="disclosure-content"><div className="results-toolbar"><button disabled={busy} onClick={() => load()}>{busy ? '正在刷新成果…' : '刷新成果'}</button>{page ? <small>本次已收录 {files.length} 个文件</small> : null}</div>
      <p className="timeline-note">收录本任务明确输出的文件和回复中嵌入的本地图片；下载的是收录时版本。点击图片可看大图。工作目录之外的文件请在桌面查看。</p>
      {files.map(f => <article className="file-card" key={f.id}>{f.image ? <ArtifactImage number={number} file={f}/> : null}<div><strong>{f.name}</strong><small>{f.size < 1024 ? `${f.size} B` : `${(f.size / 1024 / 1024).toFixed(2)} MB`} · {new Date(f.capturedAt * 1000).toLocaleDateString('zh-CN')} 收录</small></div><a className="outline" href={`/api/tasks/${number}/files/${f.id}`} download>下载</a></article>)}
      {!files.length ? <p>{busy ? '正在整理成果文件，不影响查看对话。' : !page ? '展开后检查本任务的成果文件。' : '已检查的对话中暂无可下载成果。'}</p> : null}
      {page?.skippedFiles ? <p className="timeline-note">部分成果因文件范围、类型、大小或读取限制未收录，请在桌面查看。</p> : null}
      {error ? <p className="alert" role="alert">{error}<button disabled={busy} onClick={() => load(failedOlder.current)}>重试成果</button></p> : null}
      {cursor ? <button className="more" disabled={busy} onClick={() => load(true)}>{busy ? '正在查找…' : '查找更早的成果'}</button> : <small>{!page ? '成果检查尚未完成' : '已检查到会话开始'}</small>}
    </div></details>;
}
export function Receipts({ rows }) {
  if (!rows.length) return null;
  return <details className="receipts disclosure"><summary>消息送达记录 <small>{rows.length} 条</small><span className="expand-hint">点击展开 / 收起</span></summary><div className="disclosure-content">{rows.map(row => <div className={`receipt ${row.phase}`} key={row.requestId}><strong>{row.label}</strong><small>{new Date(row.createdAt * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 编号 {row.requestId.slice(0, 8)}</small>{row.hint ? <p>{row.hint}</p> : null}</div>)}</div></details>;
}
