// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useState } from 'react';
export function ArtifactImage({ number, file, inline = false }) {
  const [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0);
  const preview = `/api/tasks/${number}/files/${file.id}/preview`;
  return <div className={inline ? 'inline-artifact-image' : 'artifact-thumbnail'}>{failed ? <div className="image-failure"><span>图片暂未加载</span><button onClick={() => { setFailed(false); setAttempt(v => v + 1); }}>重试图片</button></div> : <a href={preview} target="_blank" rel="noopener noreferrer" aria-label={`查看大图：${file.name}`}><img loading="lazy" alt={file.name} src={`${preview}?retry=${attempt}`} onError={() => setFailed(true)}/></a>}</div>;
}
export function ReplyContent({ text, number, files }) {
  // Render only locally authenticated snapshots, never arbitrary image URLs/HTML.
  const pattern = /!\[([^\]]*)\]\((?:<([^>]+)>|([^\n)]+))\)/g;
  const blocks = []; let start = 0;
  for (const match of text.matchAll(pattern)) {
    blocks.push(text.slice(start, match.index));
    let path = match[2] || match[3];
    try { path = decodeURIComponent(path).replace(/:\d+$/, ''); } catch {}
    const file = files.find(f => f.image && f.sourcePath === path);
    blocks.push(file ? <ArtifactImage key={match.index} number={number} file={file} inline/> : <span key={match.index} className="image-unavailable">〔图片：{match[1] || '未命名'}；尚未收录，可在成果区刷新或查找更早成果〕</span>);
    start = match.index + match[0].length;
  }
  blocks.push(text.slice(start));
  return blocks;
}
