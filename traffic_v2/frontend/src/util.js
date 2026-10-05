import { useEffect, useRef } from 'react';

export const LABELS = {
  accident: { name: 'Accident', tone: 'red' },
  sudden_stop: { name: 'Sudden stop', tone: 'orange' },
  congestion: { name: 'Congestion', tone: 'amber' },
  normal: { name: 'Normal', tone: 'green' },
};

export const STATUS = {
  active: { name: 'Recording', tone: 'blue' },
  pending_review: { name: 'Needs review', tone: 'orange' },
  confirmed: { name: 'Confirmed', tone: 'red' },
  dismissed: { name: 'Dismissed', tone: 'gray' },
};

export const STATE_TONE = {
  NORMAL: 'green', LOADING: 'gray', STARTING: 'gray', WARNING: 'amber', ACCIDENT: 'red',
  SUDDEN_STOP: 'orange', CONGESTION: 'amber', STOPPED: 'gray', FINISHED: 'blue', ERROR: 'red',
};

export const AUTH_TYPES = { police: 'Police', hospital: 'Hospital', traffic_control: 'Traffic control', fire: 'Fire' };
export const AUTH_COLORS = { police: '#2563eb', hospital: '#16a34a', traffic_control: '#9333ea', fire: '#ea580c' };

export function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function timeAgo(iso) {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function haversineKm(lat1, lng1, lat2, lng2) {
  const r = 6371.0088, rad = (x) => (x * Math.PI) / 180;
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export const fmtSecs = (s) => {
  if (s == null) return '-';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m}m ${r}s` : `${r}s`;
};

/** Run fn now and every `ms` while mounted. fn may be async; errors are passed to onError. */
export function usePoll(fn, ms, deps = []) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    let stop = false, timer;
    const tick = async () => {
      try { await ref.current(); } catch { /* shown by the caller's own error state */ }
      if (!stop) timer = setTimeout(tick, ms);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps]);
}
