import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, url } from '../api.js';
import MapView from '../components/MapView.jsx';
import { Badge, Card, ErrorBox, LabelBadge, SeverityBadge, StatusBadge } from '../components/ui.jsx';
import { useHealth } from '../health.jsx';
import { useLiveEvents } from '../live.jsx';
import { AUTH_COLORS, AUTH_TYPES, fmtSecs, fmtTime, haversineKm, usePoll } from '../util.js';

const ALERT_TONE = { drafted: 'gray', dry_run: 'blue', sent: 'green', failed: 'red' };
const ALERT_TEXT = { drafted: 'Draft', dry_run: 'Saved (dry-run, not sent)', sent: 'Sent', failed: 'Failed' };

function AlertCard({ alert, onChanged, onError }) {
  const [subject, setSubject] = useState(alert.subject);
  const [body, setBody] = useState(alert.body);
  const [busy, setBusy] = useState(false);
  const editable = alert.status === 'drafted';
  const dirty = subject !== alert.subject || body !== alert.body;
  const au = alert.authority || {};

  const run = async (fn) => {
    setBusy(true);
    try { await fn(); await onChanged(); } catch (e) { onError(e); } finally { setBusy(false); }
  };
  const save = () => api.patch(`/api/alerts/${alert.id}`, { subject, body });

  return (
    <div className="alert-card">
      <div className="row between">
        <div>
          <strong>{au.name || 'Authority'}</strong>{' '}
          <Badge tone="gray">{AUTH_TYPES[au.type] || au.type}</Badge>
          <div className="muted">to {alert.to_email}</div>
        </div>
        <div className="row">
          {alert.escalated ? <Badge tone="orange" title="no acknowledgement in time, sent to the next-nearest authority">escalated</Badge> : null}
          <Badge tone={ALERT_TONE[alert.status]}>{ALERT_TEXT[alert.status] || alert.status}</Badge>
        </div>
      </div>
      {alert.error && <div className="err-text">{alert.error}</div>}
      <label>Subject
        <input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label>Message
        <textarea rows={editable ? 10 : 6} value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} />
      </label>
      <div className="row between">
        <div className="muted">
          {alert.acked_at ? <span className="ok-text">Acknowledged {fmtTime(alert.acked_at)}</span>
            : (alert.status === 'sent' || alert.status === 'dry_run') ? 'Waiting for acknowledgement...' : ''}
          {alert.sent_at ? ` · sent ${fmtTime(alert.sent_at)}` : ''}
        </div>
        {(editable || alert.status === 'failed') && (
          <div className="row">
            {editable && <button className="btn small" disabled={busy}
              onClick={() => run(() => api.del(`/api/alerts/${alert.id}`))}>Discard</button>}
            {editable && <button className="btn small" disabled={busy || !dirty} onClick={() => run(save)}>Save changes</button>}
            <button className="btn small primary" disabled={busy}
              onClick={() => run(async () => { if (dirty && editable) await save(); await api.post(`/api/alerts/${alert.id}/send`); })}>
              {alert.status === 'failed' ? 'Retry send' : 'Send'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function EventDetail() {
  const { id } = useParams();
  const { health } = useHealth();
  const [ev, setEv] = useState(null);
  const [auths, setAuths] = useState([]);
  const [error, setError] = useState(null);
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('false_alarm');
  const [problems, setProblems] = useState(null);
  const [busy, setBusy] = useState(false);
  const video = useRef(null);

  const load = useCallback(async () => {
    try { setEv(await api.get(`/api/events/${id}`)); setError((e) => (e && e.fatal ? e : null)); }
    catch (e) { e.fatal = true; setError(e); }
  }, [id]);

  useEffect(() => { setEv(null); setProblems(null); load(); }, [load]);
  useEffect(() => { api.get('/api/authorities').then(setAuths).catch(() => {}); }, []);
  useLiveEvents((m) => { if (m.event && String(m.event.id) === String(id)) load(); });
  const waiting = ev && (ev.status === 'active' || !ev.clip_ready);
  usePoll(async () => { if (waiting) await load(); }, 2000, [waiting]);

  const act = async (fn) => {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const confirm = () => act(async () => {
    const r = await api.post(`/api/events/${id}/confirm`, { note: note || null });
    setProblems({ list: r.problems || [], dup: r.duplicate_warning });
  });
  const dismiss = () => act(() => api.post(`/api/events/${id}/dismiss`, { reason, note: note || null }));
  const draft = () => act(async () => {
    const r = await api.post(`/api/events/${id}/alerts/draft`);
    setProblems({ list: r.problems || [], dup: false });
  });
  const sendAll = () => act(() => api.post(`/api/events/${id}/alerts/send-all`));

  const cam = ev?.camera;
  const alertAuthIds = useMemo(() => new Set((ev?.alerts || []).map((a) => a.authority_id)), [ev]);
  const markers = useMemo(() => {
    if (!cam || cam.lat == null) return [];
    const m = [{ lat: cam.lat, lng: cam.lng, title: `Camera: ${cam.name}`, color: '#dc2626', radius: 10 }];
    auths.filter((a) => a.active).forEach((a) => m.push({
      lat: a.lat, lng: a.lng, title: `${a.name} (${AUTH_TYPES[a.type] || a.type})`,
      color: AUTH_COLORS[a.type] || '#475569', radius: alertAuthIds.has(a.id) ? 9 : 5,
    }));
    return m;
  }, [cam, auths, alertAuthIds]);
  const lines = useMemo(() => (cam && cam.lat != null
    ? auths.filter((a) => alertAuthIds.has(a.id)).map((a) => ({ from: [cam.lat, cam.lng], to: [a.lat, a.lng], color: AUTH_COLORS[a.type] }))
    : []), [cam, auths, alertAuthIds]);

  if (error && error.fatal) return <div className="page"><ErrorBox error={error} /><Link to="/events">← back to events</Link></div>;
  if (!ev) return <div className="page muted">Loading...</div>;

  const reviewable = ev.status === 'pending_review';
  const offset = ev.clip_offset_s ?? 0;
  const dur = ev.clip_duration_s || 0;
  const drafted = (ev.alerts || []).filter((a) => a.status === 'drafted').length;
  const dryRun = health && health.send_mode !== "smtp";

  return (
    <div className="page">
      <div className="crumbs"><Link to="/events">← Events</Link></div>
      <div className="row between wrap">
        <h1>Event #{ev.id}</h1>
        <div className="row"><LabelBadge label={ev.label} /><SeverityBadge severity={ev.severity} /><StatusBadge status={ev.status} /></div>
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />

      <div className="grid2">
        <div>
          <Card title="Evidence clip">
            {ev.clip_ready ? (
              <>
                <video ref={video} className="player" controls preload="metadata" src={url(`/api/events/${ev.id}/clip`)}
                  onLoadedMetadata={(e) => { if (offset > 2) e.currentTarget.currentTime = Math.max(0, offset - 2); }} />
                <div className="timeline" title="red mark = when the alert fired">
                  <div className="mark" style={{ left: `${dur ? Math.min(100, (offset / dur) * 100) : 0}%` }} />
                </div>
                <div className="row between">
                  <span className="muted">Alert fires at {fmtSecs(offset)} of {fmtSecs(dur)} (pre-roll before, post-roll after)</span>
                  <div className="row">
                    <button className="btn small" onClick={() => { video.current.currentTime = Math.max(0, offset - 2); video.current.play(); }}>Jump to alert</button>
                    <a className="btn small" href={url(`/api/events/${ev.id}/clip`)} download={`event_${ev.id}.mp4`}>Download</a>
                  </div>
                </div>
              </>
            ) : (
              <div className="empty">{ev.status === 'active' ? 'Still recording the clip... this page updates by itself.' : 'Clip not available.'}</div>
            )}
          </Card>

          <Card title="Location">
            {cam && cam.lat != null
              ? <MapView height={300} markers={markers} lines={lines} />
              : <div className="alertbox warn">This camera has no coordinates, so no nearby authority can be found. Set them on the <Link to="/cameras">Cameras</Link> page.</div>}
            <div className="legend">
              <span><i style={{ background: '#dc2626' }} /> camera</span>
              {Object.entries(AUTH_TYPES).map(([k, n]) => <span key={k}><i style={{ background: AUTH_COLORS[k] }} /> {n}</span>)}
            </div>
          </Card>
        </div>

        <div>
          <Card title="Details">
            <table className="kv"><tbody>
              <tr><td>Camera</td><td>{ev.camera_name}</td></tr>
              <tr><td>Started</td><td>{fmtTime(ev.started_at)}</td></tr>
              <tr><td>Peak probability</td><td>{ev.peak_prob != null ? `${Math.round(ev.peak_prob * 100)}%` : '-'}</td></tr>
              <tr><td>Merged repeats</td><td>{ev.merged_count || 0}</td></tr>
              {ev.duplicate_of && <tr><td>Duplicate of</td><td><Link to={`/events/${ev.duplicate_of}`}>#{ev.duplicate_of}</Link></td></tr>}
              {ev.reviewer && <tr><td>Reviewed by</td><td>{ev.reviewer} · {fmtTime(ev.reviewed_at)}</td></tr>}
              {ev.dismiss_reason && <tr><td>Dismissed as</td><td>{ev.dismiss_reason.replace('_', ' ')}</td></tr>}
              {ev.review_note && <tr><td>Note</td><td>{ev.review_note}</td></tr>}
            </tbody></table>
            <img className="snap" alt="snapshot at alert time" src={url(`/api/events/${ev.id}/snapshot`)}
              onError={(e) => { e.currentTarget.style.display = 'none'; }} />
          </Card>

          {(ev.status === 'active' || reviewable) && (
            <Card title="Operator review" className="review">
              {ev.status === 'active'
                ? <div className="muted">Review unlocks when the clip is finished recording.</div>
                : (
                  <>
                    <p className="muted">Watch the clip. <strong>Confirm</strong> only if this is real. Confirming drafts emails to the nearest
                      authorities; nothing is sent until you press Send.</p>
                    <label>Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="what you saw" /></label>
                    <div className="row">
                      <button className="btn danger" disabled={busy} onClick={confirm}>Confirm real event</button>
                      <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="dismiss reason">
                        <option value="false_alarm">False alarm</option>
                        <option value="duplicate">Duplicate</option>
                        <option value="other">Other</option>
                      </select>
                      <button className="btn" disabled={busy} onClick={dismiss}>Dismiss</button>
                    </div>
                    <div className="hint">False alarms are saved as hard negatives to improve the model (Training page).</div>
                  </>
                )}
            </Card>
          )}

          {problems && (problems.list.length > 0 || problems.dup) && (
            <div className="alertbox warn">
              {problems.dup && <div>An alert for a very similar event was already raised recently. Check before sending.</div>}
              {problems.list.map((p, i) => <div key={i}>{p}</div>)}
              <div className="muted">Fix: <Link to="/authorities">add authorities</Link> or <Link to="/cameras">set camera coordinates</Link>, then press "Draft alerts".</div>
            </div>
          )}

          {ev.status === 'confirmed' && (
            <Card title="Alerts to authorities"
              actions={<>
                <button className="btn small" disabled={busy} onClick={draft}>Draft alerts</button>
                {drafted > 1 && <button className="btn small primary" disabled={busy} onClick={sendAll}>Send all ({drafted})</button>}
              </>}>
              {dryRun && <div className="alertbox info">Dry-run mode: "Send" saves the email to the outbox, nothing leaves your machine.</div>}
              {health && health.send_mode === 'smtp' && !health.test_recipient_set &&
                <div className="alertbox warn">Real email mode with NO test recipient: emails go to the real authority addresses.</div>}
              {(ev.alerts || []).length === 0
                ? <div className="empty">No drafts yet. Press "Draft alerts" to prepare emails for the nearest authorities.</div>
                : ev.alerts.map((a) => <AlertCard key={a.id} alert={a} onChanged={load} onError={setError} />)}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
