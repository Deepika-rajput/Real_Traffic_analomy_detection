import React, { useCallback, useEffect, useState } from 'react';
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { getKey, getOperator, setKey, setOperator } from './api.js';
import { Badge, Modal } from './components/ui.jsx';
import { HealthProvider, useHealth } from './health.jsx';
import { LiveProvider, useLive, useLiveEvents } from './live.jsx';
import Authorities from './pages/Authorities.jsx';
import Cameras from './pages/Cameras.jsx';
import Dashboard from './pages/Dashboard.jsx';
import EventDetail from './pages/EventDetail.jsx';
import Events from './pages/Events.jsx';
import Training from './pages/Training.jsx';
import { LABELS } from './util.js';

function Toasts() {
  const nav = useNavigate();
  const [toasts, setToasts] = useState([]);
  useLiveEvents((m) => {
    if (m.type !== 'event' || m.action !== 'created') return;
    const e = m.event;
    const t = { id: `${e.id}-${Date.now()}`, event: e };
    setToasts((x) => [...x.slice(-3), t]);
    setTimeout(() => setToasts((x) => x.filter((y) => y.id !== t.id)), 12000);
  });
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <button key={t.id} className={`toast ${LABELS[t.event.label]?.tone || 'gray'}`}
          onClick={() => { setToasts((x) => x.filter((y) => y.id !== t.id)); nav(`/events/${t.event.id}`); }}>
          <strong>New {LABELS[t.event.label]?.name || t.event.label}</strong>
          <span>{t.event.camera_name}, click to review</span>
        </button>
      ))}
    </div>
  );
}

function SettingsModal({ onClose }) {
  const [key, setK] = useState(getKey());
  const [op, setO] = useState(getOperator());
  return (
    <Modal title="Settings" onClose={onClose}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); setKey(key.trim()); setOperator(op.trim()); onClose(); window.location.reload(); }}>
        <label>Your name (recorded when you confirm or dismiss)<input value={op} onChange={(e) => setO(e.target.value)} placeholder="e.g. Deepika" /></label>
        <label>API key (only if the server has API_KEY set)<input type="password" value={key} onChange={(e) => setK(e.target.value)} /></label>
        <button className="btn primary">Save</button>
      </form>
    </Modal>
  );
}

function Shell() {
  const { health, stats, offline } = useHealth();
  const { connected } = useLive();
  const [settings, setSettings] = useState(false);
  const [needKey, setNeedKey] = useState(false);
  useEffect(() => {
    const f = () => setNeedKey(true);
    window.addEventListener('tm-auth', f);
    return () => window.removeEventListener('tm-auth', f);
  }, []);
  const pending = stats?.by_status?.pending_review || 0;
  const link = useCallback(({ isActive }) => `nav-link ${isActive ? 'on' : ''}`, []);

  return (
    <>
      <header className="top">
        <div className="brand">🚦 Traffic Monitor</div>
        <nav>
          <NavLink to="/" end className={link}>Dashboard</NavLink>
          <NavLink to="/events" className={link}>Events{pending > 0 && <span className="count">{pending}</span>}</NavLink>
          <NavLink to="/cameras" className={link}>Cameras</NavLink>
          <NavLink to="/authorities" className={link}>Authorities</NavLink>
          <NavLink to="/training" className={link}>Training</NavLink>
        </nav>
        <div className="top-right">
          {health?.mock_detector && <Badge tone="amber" title="scripted fake alerts, not your model">MOCK DETECTOR</Badge>}
          {health && health.send_mode !== 'smtp' && <Badge tone="blue" title="emails are saved, never sent">DRY-RUN EMAIL</Badge>}
          <span className={`dot ${connected ? 'on' : ''}`} title={connected ? 'live updates connected' : 'live updates disconnected'} />
          <button className="icon" onClick={() => setSettings(true)} aria-label="settings" title="Settings">⚙</button>
        </div>
      </header>
      {offline && <div className="banner error">Cannot reach the backend. Is it running? (<code>docker compose up</code>)</div>}
      {needKey && <div className="banner warn">The server needs an API key. <button className="link" onClick={() => setSettings(true)}>Enter it in settings</button></div>}
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/events" element={<Events />} />
          <Route path="/events/:id" element={<EventDetail />} />
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/authorities" element={<Authorities />} />
          <Route path="/training" element={<Training />} />
          <Route path="*" element={<div className="page"><h1>Page not found</h1></div>} />
        </Routes>
      </main>
      <Toasts />
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
    </>
  );
}

export default function App() {
  return (
    <HealthProvider>
      <LiveProvider>
        <Shell />
      </LiveProvider>
    </HealthProvider>
  );
}
