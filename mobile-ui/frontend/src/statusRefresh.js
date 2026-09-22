// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
// Read existing summaries with bounded concurrency. This never connects, opens
// or sends to a desktop task, and never retries a failed request automatically.
export const STATUS_REFRESH_LIMIT = 8;
export async function refreshListedTasks(tasks, { read, alive, onResult, onProgress }) {
  let next = 0, checked = 0, unknown = 0, failed = 0;
  const unique = [...new Map(tasks.map(task => [task.number, task])).values()].slice(0, STATUS_REFRESH_LIMIT);
  async function worker() {
    while (alive() && next < unique.length) {
      const task = unique[next++];
      let result;
      try {
        result = await read(task.number);
        if (result.number !== task.number || (task.threadId && result.threadId !== task.threadId)) throw new Error('任务身份未匹配');
      } catch (error) {
        if (error.status === 401) throw error;
        failed++;
        result = { number: task.number, status: 'unknown', statusLabel: '状态未取得', live: false, canSend: false,
          feedback: '本次查询失败，稍后可再次刷新', refreshFailed: true, checkedAt: Date.now() / 1000 };
      }
      if (!alive()) return;
      if (!result.live || result.status === 'unknown') unknown++;
      checked++;
      onResult(result);
      onProgress({ checked, total: unique.length, unknown, failed, loading: true });
    }
  }
  await Promise.all([worker(), worker()]);
  return { checked, total: unique.length, unknown, failed, loading: false, at: Date.now() };
}
