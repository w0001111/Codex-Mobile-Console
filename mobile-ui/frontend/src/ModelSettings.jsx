// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useState } from 'react';
import { api, post, requestId } from './api';
export function ModelSettings({ number, settings, canChange, working, status, onBusyChange, refresh, onAuthError }) {
  const [editing, setEditing] = useState(false), [options, setOptions] = useState([]), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const [model, setModel] = useState(''), [effort, setEffort] = useState(''), [revision, setRevision] = useState(''), [notice, setNotice] = useState('');
  const chosen = options.find(row => row.id === model);
  const valid = chosen?.efforts.some(row => row.id === effort);
  async function openEditor() {
    if (editing) { setEditing(false); return; }
    setEditing(true); setNotice(''); setLoading(true);
    const initial = settings; setRevision(initial?.revision || ''); setModel(initial?.model || '');
    try { const data = await api('models'); setOptions(data.models); const row = data.models.find(r => r.id === initial?.model); setEffort(row?.efforts.some(e => e.id === initial?.effort) ? initial.effort : row?.defaultEffort || ''); }
    catch (e) { setNotice(e.message); if (e.status === 401) onAuthError(); }
    finally { setLoading(false); }
  }
  function changeModel(value) { const row = options.find(r => r.id === value); setModel(value); setEffort(old => row?.efforts.some(e => e.id === old) ? old : row?.defaultEffort || ''); }
  async function save(e) {
    e.preventDefault(); if (!valid || saving || working || !canChange) return;
    setSaving(true); onBusyChange(true); setNotice('');
    try { const result = await post(`tasks/${number}/model-settings`, { model, effort, expectedRevision: revision, requestId: requestId() }); setNotice(result.message); if (result.status === 'confirmed') setEditing(false); await refresh(); }
    catch (e) { setNotice(e.status === 409 ? e.message : e.status === 400 ? e.message : '设置结果待核对，请刷新当前模型后再操作。'); if (e.status === 401) onAuthError(); }
    finally { setSaving(false); onBusyChange(false); }
  }
  return <section className="model-settings"><div className="model-summary"><span><strong>{settings?.model || '模型待查询'}</strong><small>推理强度：{settings?.known ? settings.effortLabel : '待查询'}</small></span><button className="model-toggle" disabled={working || !settings?.known || !canChange} onClick={openEditor}>{editing ? '收起' : '切换'}</button></div>
    {!canChange ? <p className="model-hint">{status === 'active' ? '本轮运行中，结束后可切换下一轮设置。' : status === 'error' ? '上轮出错，模型设置需恢复空闲后再切换。' : '需先连接会话并确认空闲，才能切换。'}</p> : null}
    {editing ? <form className="model-form" onSubmit={save}><p className="model-hint">仅修改这个原会话，从下一轮生效。选项来自本机 Codex 当前可用模型。</p>{loading ? <p>正在读取可用模型…</p> : <><label htmlFor="session-model">模型</label><select id="session-model" value={model} disabled={saving} onChange={e => changeModel(e.target.value)}>{!options.some(r => r.id === model) ? <option value={model} disabled>{model || '请选择模型'}</option> : null}{options.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select><label htmlFor="session-effort">推理强度</label><select id="session-effort" value={effort} disabled={saving || !chosen} onChange={e => setEffort(e.target.value)}>{!valid ? <option value="" disabled>请选择推理强度</option> : null}{chosen?.efforts.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>{revision && settings?.revision !== revision ? <p className="alert">桌面设置已变化，请收起后重新打开选项。</p> : null}<button className="primary" disabled={saving || working || !canChange || !valid || settings?.revision !== revision}>{saving ? '正在保存并核对…' : '保存本会话设置'}</button></>}</form> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
  </section>;
}
