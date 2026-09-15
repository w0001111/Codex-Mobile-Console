// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useEffect, useRef, useState } from 'react';
import { readPage } from './api';
function duration(mins) {
  if (!mins) return '额度窗口';
  if (mins % 1440 === 0) return `${mins / 1440} 天额度`;
  if (mins % 60 === 0) return `${mins / 60} 小时额度`;
  return `${mins} 分钟额度`;
}
function Bucket({ bucket }) {
  return <div className="quota-bucket"><strong>{bucket.name}</strong>{bucket.windows.map(w => <div className="quota-window" key={w.id}><div><span>{duration(w.durationMinutes)}</span><b>{w.remainingPercent == null ? '暂不可用' : `剩余 ${w.remainingPercent}%`}</b></div>{w.remainingPercent != null ? <progress aria-label={`${bucket.name} ${duration(w.durationMinutes)}剩余`} value={w.remainingPercent} max="100"/> : null}<small>{w.resetsAt ? `${new Date(w.resetsAt * 1000).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})} 重置` : '重置时间未提供'}</small></div>)}</div>;
}
export function Quota({ onAuthError }) {
  const [data,setData]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const active=useRef(true),reading=useRef(false);
  async function load() {
    if (reading.current) return; reading.current=true;setBusy(true);
    try { const value=await readPage('quota',{alive:()=>active.current});if (value && active.current) {setData(value);setError('');} }
    catch(e) {if(active.current){setError(e.message);if(e.status===401)onAuthError?.();}}
    finally {reading.current=false;if(active.current)setBusy(false);}
  }
  useEffect(()=>{active.current=true;load();const timer=setInterval(()=>{if(!document.hidden)load();},60000);return()=>{active.current=false;clearInterval(timer);};},[]);
  const rows=data?.buckets || [];
  return <section className="quota-card" aria-label="账号额度"><div className="quota-heading"><h2>账号额度</h2><button disabled={busy} onClick={load}>{busy?'读取中…':'刷新额度'}</button></div><p>整个 Codex 账号共享 · 每分钟更新</p>{rows[0]?<Bucket bucket={rows[0]}/>:<p>{error || (busy?'正在读取额度…':'当前未提供额度数据')}</p>}{rows.length>1?<details><summary>其他模型额度（{rows.length-1}）</summary>{rows.slice(1).map(b=><Bucket key={b.id} bucket={b}/>)}</details>:null}{error && data?<p className="quota-warning">更新失败，显示上次读取结果。</p>:null}{data?.observedAt?<small>更新于 {new Date(data.observedAt*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</small>:null}</section>;
}
