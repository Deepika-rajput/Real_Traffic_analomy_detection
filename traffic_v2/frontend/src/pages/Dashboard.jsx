import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, url } from '../api.js';
import { Card, Empty, ErrorBox, LabelBadge, SeverityBadge, StateBadge, StatusBadge } from '../components/ui.jsx';
import { useLiveEvents } from '../live.jsx';
import { useHealth } from '../health.jsx';
import { fmtTime, timeAgo, usePoll } from '../util.js';

function Stat({ label, value, tone, to }) {
  const body = (
    <div className={`stat ${tone || ''}`}>
      <div className="stat-value">{value ?? '-'}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
  return to ? <Link to={to} className="plain">{body}</Link> : body;
}

function CameraTile({ cam, onChanged, onError }) {
  const st = cam.status || {};
  const running = !!st.running;
  const act = async (what) => {
    try { await api.post(`/api/cameras/${cam.id}/${what}`); onChanged(); } catch (e) { onError(e); }
  };
  return (
    <div className="tile">
      <div className="tile-media">
        {running
          ? <img className="live" alt={`${cam.name} live`} src={url(`/api/cameras/${cam.id}/stream`)} />
          : <div className="tile-off">{st.state === 'FINISHED' ? 'Finished' : st.state === 'ERROR' ? 'Error' : 'Stopped'}</div>}
        <div className="tile-state"><StateBadge state={st.state || 'STOPPED'} /></div>
      </div>
      <div className="tile-body">
        <div className="tile-title">
          <strong>{cam.name}</strong>
          {cam.kind === 'upload' && <span className="muted"> · upload</span>}
        </div>
        {st.error && <div className="err-text">{st.error}</div>}
        <div className="row between">
          <Link className="link" to={`/events?camera_id=${cam.id}`}>events</Link>
          {running
            ? <button className="btn small" onClick={() => act('stop')}>Stop</button>
            : <button className="btn small primary" onClick={() => act('start')}>Start</button>}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { stats } = useHealth();
  const [cams, setCams] = useState(null);
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    const [c, e] = await Promise.all([api.get('/api/cameras'), api.get('/api/events?limit=8')]);
    setCams(c); setEvents(e.items);
  }, []);
  usePoll(load, 3000);
  useLiveEvents(() => load().catch(() => {}));

  const pending = (stats?.by_status?.pending_review || 0);
  const active = (stats?.by_status?.active || 0);

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="stats">
        <Stat label="Need review" value={pending} tone={pending ? 'warn' : ''} to="/events?tab=review" />
        <Stat label="Recording now" value={active} />
        <Stat label="Cameras running" value={stats?.cameras_running} />
        <Stat label="Confirmed events" value={stats?.confirmed} />
        <Stat label="Operator-measured precision"
          value={stats?.operator_precision == null ? 'n/a' : `${Math.round(stats.operator_precision * 100)}%`} />
      </div>

      <Card title="Live cameras" actions={<Link to="/cameras" className="link">manage cameras</Link>}>
        {cams === null ? <Empty>Loading...</Empty>
          : cams.length === 0 ? <Empty>No cameras yet. <Link to="/cameras">Add a camera or upload a video</Link> to start.</Empty>
            : <div className="tiles">{cams.map((c) => <CameraTile key={c.id} cam={c} onChanged={load} onError={setError} />)}</div>}
      </Card>

      <Card title="Latest events" actions={<Link to="/events" className="link">all events</Link>}>
        {events === null ? <Empty>Loading...</Empty>
          : events.length === 0 ? <Empty>No events yet. Detected anomalies will appear here live.</Empty>
            : (
              <div className="list">
                {events.map((e) => (
                  <Link key={e.id} to={`/events/${e.id}`} className="list-row plain">
                    <img className="thumb" alt="" src={url(`/api/events/${e.id}/snapshot`)}
                      onError={(ev) => { ev.currentTarget.style.visibility = 'hidden'; }} />
                    <div className="grow">
                      <div className="row"><LabelBadge label={e.label} /><SeverityBadge severity={e.severity} /><StatusBadge status={e.status} /></div>
                      <div className="muted">{e.camera_name} · {fmtTime(e.started_at)} ({timeAgo(e.started_at)})</div>
                    </div>
                    <span className="link">review →</span>
                  </Link>
                ))}
              </div>
            )}
      </Card>
    </div>
  );
}
