// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React from 'react';
import author from '../../../AUTHOR.json';
import version from '../../../VERSION?raw';
import license from '../../../LICENSE?raw';

export function About({ back }) {
  return <main className="about-page">
    <button onClick={back}>← 返回</button>
    <p className="about-eyebrow">关于本应用</p>
    <h1>{author.project}</h1>
    <p>在自己的设备与服务器上，管理本地 Codex 会话。</p>
    <dl className="about-facts">
      <div><dt>项目作者</dt><dd><a href={author.github} target="_blank" rel="noopener noreferrer">{author.author} ↗</a></dd></div>
      <div><dt>当前版本</dt><dd>{version.trim()}</dd></div>
      <div><dt>开源许可</dt><dd>{author.license}</dd></div>
    </dl>
    <p className="about-copyright">Copyright © {author.copyrightYear} {author.author}</p>
    <details className="about-disclosure"><summary>查看 MIT 许可全文</summary><pre>{license}</pre></details>
    <details className="about-disclosure"><summary>发布包来源验证</summary>
      <p>下载包附有独立签名，可按包内 SIGNING.md 验证。请先从你已确认的作者 GitHub 页面核对公钥指纹。</p>
      <code>{author.signingFingerprint}</code>
      <p>这里展示的是构建时的发布公钥信息，不代表当前服务器内容已通过自动验签。</p>
    </details>
    <p className="about-note">基于 cc-connect 等开源项目，第三方署名与许可见包内 THIRD_PARTY.md 和 THIRD_PARTY_LICENSES.md。本项目并非 OpenAI 或消息平台官方应用。</p>
  </main>;
}
