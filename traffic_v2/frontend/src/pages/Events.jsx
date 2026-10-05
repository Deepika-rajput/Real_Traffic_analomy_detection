import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, url } from '../api.js';
import { Card, Empty, ErrorBox, LabelBadge, SeverityBadge, StatusBadge } from '../components/ui.jsx';
import { useLiveEvents } from '../live.jsx';
import { fmtSecs, fmtTime, LABELS } from '../util.js';

const TABS = {
  review: { name: 'Needs review', status: 'active,pending_review' },
  confirmed: { name: 'Confirmed', status: 'confirmed' },
  dismissed: { name: 'Dismissed', status: 'dismissed' },
  all: { name: 'All', status: '' },
};
const PAGE = 20;

export default function Events() {
  const [sp, setSp] = useSearchParams();
  const tab = TABS[sp.get('tab')] ? sp.get('tab') : 'review';
  const label = sp.get('label') || '';
  const severity = sp.get('severity') || '';
  const cameraId = sp.get('camera_id') || '';
  const page = Math.max(0, parseInt(sp.get('page') || '0', 10) || 0);

  const [data, setData] = useState(null);
  const [cams, setCams] = useState([]);
  const [error, setError] = useState(null);

  const set = (k, v) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v); else n.delete(k);
    if (k !== 'page') n.delete('page');
    setSp(n, { replace: true });
  };

  const load = useCallback(async () => {
    const q = new URLSearchParams({ limit: PAGE, offset: page * PAGE });
    if (TABS[tab].status) q.set('status', TABS[tab].status);
    if (label) q.set('label', label);
    if (severity) q.set('severity', severity);
    if (cameraId) q.set('camera_id', cameraId);
    try { setData(await api.get(`/api/events?${q}`)); setError(null); } catch (e) { setError(e); }
  }, [tab, label, severity, cameraId, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get('/api/cameras').then(setCams).catch(() => {}); }, []);

  const timer = useRef();
  useLiveEvents(() => { clearTimeout(timer.current); timer.current = setTimeout(load, 400); });
  useEffect(() => () => clearTimeout(timer.current), []);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  return (
    <div className="page">
      <h1>Events</h1>
      <div className="tabs">
        {Object.entries(TABS).map(([k, t]) => (
          <button key={k} className={`tab ${k === tab ? 'on' : ''}`} onClick={() => set('tab', k === 'review' ? '' : k)}>{t.name}</button>
        ))}
      </div>
      <div className="filters">
        <select value={label} onChange={(e) => set('label', e.target.value)} aria-label="type">
          <option value="">All types</option>
          {['accident', 'sudden_stop', 'congestion'].map((l) => <option key={l} value={l}>{LABELS[l].name}</option>)}
        </select>
        <select value={severity} onChange={(e) => set('severity', e.target.value)} aria-label="severity">
          <option value="">Any severity</option>
          {['high', 'medium', 'low'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={cameraId} onChange={(e) => set('camera_id', e.target.value)} aria-label="camera">
          <option value="">All cameras</option>
          {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {data && <span className="muted">{data.total} event{data.total === 1 ? '' : 's'}</span>}
      </div>
      <ErrorBox error={error} />
      <Card>
        {data === null ? <Empty>Loading...</Empty>
          : data.items.length === 0 ? <Empty>Nothing here{tab === 'review' ? ': no events waiting for review.' : '.'}</Empty>
            : (
              <div className="list">
                {data.items.map((e) => (
                  <Link key={e.id} to={`/events/${e.id}`} className="list-row plain">
                    <img className="thumb big" alt="" src={url(`/api/events/${e.id}/snapshot`)}
                      onError={(ev) => { ev.currentTarget.style.visibility = 'hidden'; }} />
                    <div className="grow">
                      <div className="row">
                        <LabelBadge label={e.label} /><SeverityBadge severity={e.severity} /><StatusBadge status={e.status} />
                        {e.merged_count > 0 && <span className="muted">+{e.merged_count} merged</span>}
                      </div>
                      <div><strong>{e.camera_name}</strong> <span className="muted">· {fmtTime(e.started_at)}</span></div>
                      <div className="muted">
                        peak {e.peak_prob != null ? `${Math.round(e.peak_prob * 100)}%` : '-'} · clip {e.clip_path ? fmtSecs(e.clip_duration_s) : 'recording...'}
                      </div>
                    </div>
                    <span className="link">open →</span>
                  </Link>
                ))}
              </div>
            )}
      </Card>
      {pages > 1 && (
        <div className="row center">
          <button className="btn small" disabled={page === 0} onClick={() => set('page', String(page - 1))}>← Prev</button>
          <span className="muted">page {page + 1} / {pages}</span>
          <button className="btn small" disabled={page + 1 >= pages} onClick={() => set('page', String(page + 1))}>Next →</button>
        </div>
      )}
    </div>
  );
}
