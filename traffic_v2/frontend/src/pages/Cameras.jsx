import React, { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import LocationPicker from '../components/LocationPicker.jsx';
import { Card, Empty, ErrorBox, Modal, StateBadge } from '../components/ui.jsx';
import { usePoll } from '../util.js';

const toNum = (v) => (v === '' || v == null ? null : Number(v));

function CameraForm({ initial, onSubmit, submitText }) {
  const [f, setF] = useState({
    name: '', source: '', lat: '', lng: '', road_type: 'highway', loop: true, realtime: true, ...initial,
  });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const submit = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try {
      await onSubmit({ name: f.name, source: f.source, lat: toNum(f.lat), lng: toNum(f.lng),
        road_type: f.road_type, loop: f.loop, realtime: f.realtime });
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="form">
      <ErrorBox error={err} />
      <label>Name<input required value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Highway 101 - Camera 4" /></label>
      <label>Source
        <input required value={f.source} onChange={(e) => set('source', e.target.value)}
          placeholder="rtsp://...   or   /app/videos/accident/acc1.mp4   or   0 (webcam)" />
      </label>
      <div className="hint">Inside Docker, file paths are paths <em>in the container</em>: your project's <code>videos/</code> folder is <code>/app/videos/</code>.</div>
      <div className="row">
        <label className="check"><input type="checkbox" checked={f.loop} onChange={(e) => set('loop', e.target.checked)} /> Loop file (acts like a live camera)</label>
        <label className="check"><input type="checkbox" checked={f.realtime} onChange={(e) => set('realtime', e.target.checked)} /> Play at real-time speed</label>
      </div>
      <label>Road type
        <select value={f.road_type} onChange={(e) => set('road_type', e.target.value)}>
          <option value="highway">Highway</option><option value="junction">Junction</option><option value="urban">Urban road</option>
        </select>
      </label>
      <h4>Camera location <span className="muted">(needed to find the nearest authority)</span></h4>
      <LocationPicker value={{ lat: f.lat, lng: f.lng }} onChange={(v) => setF((x) => ({ ...x, ...v }))} />
      <button className="btn primary" disabled={busy}>{submitText}</button>
    </form>
  );
}

function UploadCard({ onDone }) {
  const nav = useNavigate();
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [loc, setLoc] = useState({ lat: '', lng: '' });
  const [pct, setPct] = useState(null);
  const [err, setErr] = useState(null);
  const [cam, setCam] = useState(null);
  const [status, setStatus] = useState(null);

  usePoll(async () => {
    if (cam && !(status && status.finished)) setStatus(await api.get(`/api/cameras/${cam.id}/status`));
  }, 1500, [cam, status && status.finished]);

  const submit = async (e) => {
    e.preventDefault(); setErr(null); setPct(0); setStatus(null);
    const fd = new FormData();
    fd.append('file', file);
    if (name) fd.append('name', name);
    if (loc.lat !== '') fd.append('lat', loc.lat);
    if (loc.lng !== '') fd.append('lng', loc.lng);
    try {
      const r = await api.upload('/api/uploads', fd, setPct);
      setCam(r.camera); onDone();
    } catch (x) { setErr(x); }
    setPct(null);
  };

  return (
    <Card title="Analyze an uploaded video">
      <p className="muted">Upload any traffic video. It runs through the same model once, and detected events appear in the review queue.</p>
      <form onSubmit={submit} className="form">
        <ErrorBox error={err} />
        <label>Video file<input type="file" accept="video/*,.mkv" required onChange={(e) => setFile(e.target.files[0])} /></label>
        <label>Name (optional)<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <details>
          <summary>Where was it filmed? (optional, needed to email authorities)</summary>
          <LocationPicker value={loc} onChange={setLoc} height={200} />
        </details>
        <button className="btn primary" disabled={!file || pct !== null}>{pct !== null ? `Uploading ${Math.round(pct * 100)}%` : 'Upload and analyze'}</button>
      </form>
      {cam && (
        <div className="alertbox info">
          <div><strong>{cam.name}</strong>: <StateBadge state={status?.state || 'STARTING'} /> {status ? `${status.frames || 0} frames` : ''}</div>
          {status?.error && <div className="err-text">{status.error}</div>}
          {status?.finished && !status.error && (
            <button className="btn small primary" onClick={() => nav(`/events?tab=all&camera_id=${cam.id}`)}>Analysis finished: view events</button>
          )}
        </div>
      )}
    </Card>
  );
}

export default function Cameras() {
  const [cams, setCams] = useState(null);
  const [error, setError] = useState(null);
  const [edit, setEdit] = useState(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => setCams(await api.get('/api/cameras')), []);
  usePoll(load, 3000);

  const act = async (fn) => { try { await fn(); await load(); } catch (e) { setError(e); } };

  return (
    <div className="page">
      <div className="row between"><h1>Cameras</h1><button className="btn primary" onClick={() => setAdding(true)}>+ Add camera</button></div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <Card>
        {cams === null ? <Empty>Loading...</Empty> : cams.length === 0 ? <Empty>No cameras yet.</Empty> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Source</th><th>Location</th><th>State</th><th /></tr></thead>
            <tbody>
              {cams.map((c) => {
                const st = c.status || {};
                return (
                  <tr key={c.id}>
                    <td><strong>{c.name}</strong>{c.kind === 'upload' && <span className="muted"> · upload</span>}<div><Link className="link" to={`/events?tab=all&camera_id=${c.id}`}>events</Link></div></td>
                    <td className="src" title={c.source}>{c.source}</td>
                    <td>{c.lat != null ? `${c.lat.toFixed(4)}, ${c.lng.toFixed(4)}` : <span className="err-text">not set</span>}</td>
                    <td><StateBadge state={st.state || 'STOPPED'} />{st.error && <div className="err-text">{st.error}</div>}</td>
                    <td className="actions">
                      {st.running
                        ? <button className="btn small" onClick={() => act(() => api.post(`/api/cameras/${c.id}/stop`))}>Stop</button>
                        : <button className="btn small primary" onClick={() => act(() => api.post(`/api/cameras/${c.id}/start`))}>Start</button>}
                      <button className="btn small" onClick={() => setEdit(c)}>Edit</button>
                      <button className="btn small danger-o" onClick={() => {
                        if (window.confirm(`Delete "${c.name}" and all its events and clips?`)) act(() => api.del(`/api/cameras/${c.id}`));
                      }}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      <UploadCard onDone={load} />

      {adding && (
        <Modal title="Add camera" onClose={() => setAdding(false)} wide>
          <CameraForm submitText="Add camera" onSubmit={async (b) => { await api.post('/api/cameras', { ...b, enabled: true }); setAdding(false); await load(); }} />
        </Modal>
      )}
      {edit && (
        <Modal title={`Edit ${edit.name}`} onClose={() => setEdit(null)} wide>
          <CameraForm submitText="Save"
            initial={{ ...edit, lat: edit.lat ?? '', lng: edit.lng ?? '', loop: !!edit.loop, realtime: !!edit.realtime }}
            onSubmit={async (b) => { const r = await api.patch(`/api/cameras/${edit.id}`, b); setEdit(null); await load(); if (r.note) setError({ message: r.note }); }} />
        </Modal>
      )}
    </div>
  );
}
