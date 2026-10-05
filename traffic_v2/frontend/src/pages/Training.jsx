import React, { useState } from 'react';
import { api } from '../api.js';
import { Card, ErrorBox } from '../components/ui.jsx';
import { useHealth } from '../health.jsx';
import { LABELS } from '../util.js';

export default function Training() {
  const { stats, refresh } = useHealth();
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState(null);
  const [label, setLabel] = useState('accident');
  const [pct, setPct] = useState(null);

  const exportNow = async () => {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await api.post('/api/training/export');
      const n = Array.isArray(r.exported) ? r.exported.length : r.exported;
      setMsg(`Exported ${typeof n === 'number' ? n : 'the'} reviewed clip(s) into your videos/ folders.`); refresh();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const upload = async (e) => {
    e.preventDefault(); setError(null); setMsg(null); setPct(0);
    const fd = new FormData(); fd.append('file', file); fd.append('label', label);
    try { const r = await api.upload('/api/training/upload', fd, setPct); setMsg(`Saved ${r.saved}`); setFile(null); e.target.reset(); }
    catch (x) { setError(x); }
    setPct(null);
  };

  return (
    <div className="page">
      <h1>Training data</h1>
      <p className="muted">Every review makes the model better: confirmed events become examples of their class, and dismissed false alarms
        become "normal" examples (the most valuable kind). This page moves them into the training folders.</p>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {msg && <div className="alertbox info">{msg}</div>}
      <div className="stats">
        <div className="stat"><div className="stat-value">{stats?.confirmed ?? '-'}</div><div className="stat-label">Confirmed</div></div>
        <div className="stat"><div className="stat-value">{stats?.false_alarms ?? '-'}</div><div className="stat-label">False alarms</div></div>
        <div className="stat"><div className="stat-value">{stats?.operator_precision == null ? 'n/a' : `${Math.round(stats.operator_precision * 100)}%`}</div><div className="stat-label">Precision (as judged by operators)</div></div>
      </div>
      <div className="grid2">
        <Card title="1. Export reviewed clips">
          <p className="muted">Copies new confirmed and dismissed clips into <code>videos/&lt;class&gt;/</code> (trimmed around the alert).</p>
          <button className="btn primary" disabled={busy} onClick={exportNow}>Export reviewed clips</button>
        </Card>
        <Card title="Or upload a labeled video">
          <form onSubmit={upload} className="form">
            <label>Video<input type="file" accept="video/*,.mkv" required onChange={(e) => setFile(e.target.files[0])} /></label>
            <label>Class
              <select value={label} onChange={(e) => setLabel(e.target.value)}>
                {Object.entries(LABELS).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
              </select>
            </label>
            <div className="hint">The WHOLE video is labeled with this class. Upload short, clean clips.</div>
            <button className="btn primary" disabled={!file || pct !== null}>{pct !== null ? `Uploading ${Math.round(pct * 100)}%` : 'Upload'}</button>
          </form>
        </Card>
      </div>
      <Card title="2. Retrain (when you have new data)">
        <p className="muted">Retraining runs on your machine, in the project folder (features of old videos are cached, so only the new ones are processed):</p>
        <pre className="code">{`# with Docker (from the project folder)
docker compose run --rm backend sh -c "python make_labels.py && python extract_features.py && python train.py"
docker compose restart backend      # loads the new temporal.pth

# or without Docker
python make_labels.py && python extract_features.py && python train.py`}</pre>
        <p className="muted">Check the TEST numbers it prints, and keep a separate <code>holdout/</code> folder for <code>evaluate_folder.py</code>.</p>
      </Card>
    </div>
  );
}
