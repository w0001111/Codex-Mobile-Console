// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { getView, saveView } from './viewState';

function snapshot(root) {
  const candidates = [...root.querySelectorAll('[data-read-key]')].filter(el => el.getClientRects().length);
  const anchor = candidates.find(el => el.getBoundingClientRect().top >= 0 && el.getBoundingClientRect().top < innerHeight / 2)
    || candidates.reverse().find(el => el.getBoundingClientRect().top < 0 && el.getBoundingClientRect().bottom > 0);
  return { y: window.scrollY, anchor: anchor?.dataset.readKey, offset: anchor?.getBoundingClientRect().top || 0 };
}
function restore(root, point) {
  if (!point) return;
  const anchor = [...root.querySelectorAll('[data-read-key]')].find(el => el.dataset.readKey === point.anchor && el.getClientRects().length);
  const top = anchor ? window.scrollY + anchor.getBoundingClientRect().top - point.offset : point.y || 0;
  window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
}

// Restore once after initial data arrives. Subsequent read-only refreshes retain
// the current visible anchor; user scrolling cancels a pending initial restore.
export function useReadingPosition(key, root, active, ready, revision) {
  const restoring = useRef(false), point = useRef(null), refreshPoint = useRef(null);
  const frame = useRef(0), dirty = useRef(false);
  const current = useRef({ active, ready }); current.current = { active, ready };
  const preserve = useCallback(() => {
    if (current.current.active && current.current.ready && !restoring.current && root.current && window.scrollY > 0) refreshPoint.current = snapshot(root.current);
  }, [root]);
  useLayoutEffect(() => {
    if (!active) return;
    restoring.current = true; point.current = getView(key).reading || null;
    window.scrollTo({ top: 0, behavior: 'instant' });
    const cancel = () => { restoring.current = false; refreshPoint.current = null; };
    const capture = () => {
      if (restoring.current || !root.current) return;
      point.current = snapshot(root.current); dirty.current = true;
    };
    const flush = () => {
      if (dirty.current && point.current) { saveView(key, { reading: point.current }); dirty.current = false; }
    };
    const scroll = () => { cancelAnimationFrame(frame.current); frame.current = requestAnimationFrame(capture); };
    window.addEventListener('scroll', scroll, { passive: true });
    const inputs = ['wheel', 'touchstart', 'pointerdown', 'keydown'];
    inputs.forEach(name => window.addEventListener(name, cancel, { passive: true }));
    const leaving = () => { capture(); flush(); };
    window.addEventListener('pagehide', leaving);
    document.addEventListener('visibilitychange', leaving);
    return () => {
      cancelAnimationFrame(frame.current);
      window.removeEventListener('scroll', scroll);
      inputs.forEach(name => window.removeEventListener(name, cancel));
      window.removeEventListener('pagehide', leaving);
      document.removeEventListener('visibilitychange', leaving);
      flush();
    };
  }, [key, active, root]);
  useLayoutEffect(() => {
    if (!active || !root.current) return;
    if (restoring.current && ready) {
      restore(root.current, point.current); restoring.current = false;
    } else if (refreshPoint.current) restore(root.current, refreshPoint.current);
    refreshPoint.current = null;
  }, [active, ready, revision, root]);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      if (dirty.current && point.current) { saveView(key, { reading: point.current }); dirty.current = false; }
    }, 500);
    return () => clearInterval(timer);
  }, [key, active]);
  return {
    preserve,
    capture: () => {
      if (active && !restoring.current && root.current) {
        point.current = snapshot(root.current); saveView(key, { reading: point.current }); dirty.current = false;
      }
    },
    isRestoring: () => restoring.current,
  };
}
