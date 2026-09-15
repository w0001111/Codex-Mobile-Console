// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useState } from 'react';
import { post, setCSRF } from './api';
export function Login({ done, onAbout }) {
  const [code, setCode] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [password, setPassword] = useState('');
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { const r = await post('pair', { code, password }); setCSRF(r.csrf); setCode(''); await done(); }
    catch (e) { setError(e.message); } finally { setPassword(''); setBusy(false); }
  }
  return <main className="login"><div className="login-mark">↗</div><h1>Codex 控制台</h1>
    <p>在已绑定的消息软件中发送“界面”获取登录码。<br/>首次使用：先在 Mac 运行「设置网页登录密码.command」，看到“密码已设置”后再登录。</p>
    <form onSubmit={submit}><label htmlFor="pair-code">一次性登录码</label>
      <input id="pair-code" autoComplete="one-time-code" placeholder="输入机器人回复中的登录码" autoCapitalize="characters" spellCheck={false} value={code} onChange={e => setCode(e.target.value)} maxLength={60}/>
      <label htmlFor="web-password">独立密码（在 Mac 单独设置，9–128 个字符）</label>
      <input id="web-password" type="password" autoComplete="current-password" placeholder="输入在 Mac 设置的独立密码" value={password} onChange={e => setPassword(e.target.value)} maxLength={128}/>
      {error && <p className="alert" role="alert">{error}</p>}
      <button className="primary" disabled={busy || !code.trim() || !password}>{busy ? '正在连接…' : '打开控制台'}</button>
    </form>
    <small>首次设置或忘记密码，请在 Mac 本机操作；消息平台登录码不能重置密码。<br/>登录码 10 分钟有效，仅用一次，请勿转发。<br/>登录最长 12 小时；闲置 30 分钟后需重新授权。<br/>Mac 需保持联网且不进入睡眠，Codex 桌面需保持打开。</small>
    <button className="about-entry" onClick={onAbout}>关于本应用</button>
  </main>;
}
