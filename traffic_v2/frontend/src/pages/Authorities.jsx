import React, { useCallback, useMemo, useState } from 'react';
import { api } from '../api.js';
import LocationPicker from '../components/LocationPicker.jsx';
import MapView from '../components/MapView.jsx';
import { Badge, Card, Empty, ErrorBox } from '../components/ui.jsx';
import { AUTH_COLORS, AUTH_TYPES, usePoll } from '../util.js';

export default function Authorities() {
  const [list, setList] = useState(null);
  const [cams, setCams] = useState([]);
  const [error, setError] = useState(null);
  const [f, setF] = useState({ name: '', type: 'police', email: '', phone: '', lat: '', lng: '' });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [a, c] = await Promise.all([api.get('/api/authorities'), api.get('/api/cameras')]);
    setList(a); setCams(c);
  }, []);
  usePoll(load, 8000);

  const markers = useMemo(() => [
    ...(list || []).filter((a) => a.active).map((a) => ({ lat: a.lat, lng: a.lng, color: AUTH_COLORS[a.type], title: `${a.name} (${AUTH_TYPES[a.type]})`, radius: 8 })),
    ...cams.filter((c) => c.lat != null).map((c) => ({ lat: c.lat, lng: c.lng, color: '#dc2626', title: `Camera: ${c.name}`, radius: 6 })),
  ], [list, cams]);

  const add = async (e) => {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api.post('/api/authorities', { name: f.name, type: f.type, email: f.email, phone: f.phone || null,
        lat: Number(f.lat), lng: Number(f.lng), active: true });
      setF({ name: '', type: 'police', email: '', phone: '', lat: '', lng: '' });
      await load();
    } catch (x) { setError(x); } finally { setBusy(false); }
  };
  const act = async (fn) => { try { await fn(); await load(); } catch (x) { setError(x); } };

  return (
    <div className="page">
      <h1>Authorities</h1>
      <p className="muted">When an operator confirms an event, emails are drafted to the <strong>nearest active</strong> authority of each
        needed type (accident: police and hospital; sudden stop and congestion: traffic control), within the configured radius.</p>
      <div className="alertbox info">Use test addresses (your own inbox, or <code>@example.com</code>) while developing. Never enter real police or hospital emails until you are ready to go live.</div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="grid2">
        <Card title="Registered authorities">
          {list === null ? <Empty>Loading...</Empty> : list.length === 0 ? <Empty>None yet. Add one on the right.</Empty> : (
            <table className="table">
              <thead><tr><th>Name</th><th>Type</th><th>Email</th><th /></tr></thead>
              <tbody>
                {list.map((a) => (
                  <tr key={a.id} className={a.active ? '' : 'off'}>
                    <td><strong>{a.name}</strong><div className="muted">{a.lat.toFixed(4)}, {a.lng.toFixed(4)}{a.phone ? ` · ${a.phone}` : ''}</div></td>
                    <td><Badge tone="gray">{AUTH_TYPES[a.type] || a.type}</Badge></td>
                    <td className="src">{a.email}</td>
                    <td className="actions">
                      <button className="btn small" onClick={() => act(() => api.patch(`/api/authorities/${a.id}`, { active: !a.active }))}>{a.active ? 'Disable' : 'Enable'}</button>
                      <button className="btn small danger-o" onClick={() => { if (window.confirm(`Remove ${a.name}?`)) act(() => api.del(`/api/authorities/${a.id}`)); }}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="legend">
            <span><i style={{ background: '#dc2626' }} /> camera</span>
            {Object.entries(AUTH_TYPES).map(([k, n]) => <span key={k}><i style={{ background: AUTH_COLORS[k] }} /> {n}</span>)}
          </div>
          <MapView height={280} markers={markers} />
        </Card>
        <Card title="Add authority">
          <form onSubmit={add} className="form">
            <label>Name<input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Central Police Station" /></label>
            <div className="row">
              <label className="grow">Type
                <select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>
                  {Object.entries(AUTH_TYPES).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
                </select>
              </label>
              <label className="grow">Phone (optional)<input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
            </div>
            <label>Email<input required type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} placeholder="control-room@example.com" /></label>
            <LocationPicker value={{ lat: f.lat, lng: f.lng }} onChange={(v) => setF({ ...f, ...v })} markers={markers} />
            <button className="btn primary" disabled={busy || f.lat === '' || f.lng === ''}>Add authority</button>
          </form>
        </Card>
      </div>
    </div>
  );
}
