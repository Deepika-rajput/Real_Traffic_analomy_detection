// End-to-end smoke test: renders the real app against a RUNNING backend (jsdom, no browser needed).
//
//   backend:  MOCK_DETECTOR=1 MOCK_SCRIPT="accident:2-6" python -m uvicorn backend.app.main:app --port 8000
//   frontend: TM_API=http://127.0.0.1:8000 TM_VIDEO=/path/to/some_video.mp4 npm test
//
// Skipped automatically when TM_API / TM_VIDEO are not set.
import React from 'react';
import { describe, expect, it, beforeAll } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WebSocket as NodeWS } from 'ws';

const API = process.env.TM_API;
const VIDEO = process.env.TM_VIDEO;
const run = API && VIDEO ? describe : describe.skip;

run('frontend against a live backend', () => {
  let App, ids = {};

  beforeAll(async () => {
    globalThis.window.__API_BASE__ = API;
    globalThis.WebSocket = NodeWS;      // Node's built-in WebSocket clashes with jsdom's Event class; 'ws' works
    // jsdom has no layout: give Leaflet's container a size so fitBounds/setView behave like in a browser
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 600 });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 300 });
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 600 });
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 300 });
    HTMLMediaElement.prototype.play = () => Promise.resolve();
    HTMLMediaElement.prototype.load = () => {};

    const post = (p, b) => fetch(API + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());
    await post('/api/authorities', { name: 'Test Police', type: 'police', email: 'police@example.com', lat: 28.62, lng: 77.21 });
    await post('/api/authorities', { name: 'Test Hospital', type: 'hospital', email: 'hospital@example.com', lat: 28.63, lng: 77.19 });
    const cam = await post('/api/cameras', { name: 'E2E camera', source: VIDEO, lat: 28.61, lng: 77.2, loop: false, realtime: false, enabled: true });
    ids.cam = cam.id;
    ({ default: App } = await import('../App.jsx'));
  });

  const open = (path) => { cleanup(); return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); };

  it('dashboard shows the camera and the backend flags', async () => {
    open('/');
    expect(await screen.findByText('E2E camera', {}, { timeout: 15000 })).toBeTruthy();
    expect(await screen.findByText('MOCK DETECTOR')).toBeTruthy();
    expect(screen.getByText('DRY-RUN EMAIL')).toBeTruthy();
  });

  it('a detected event appears in the review queue', async () => {
    open('/events');
    const link = await waitFor(() => {
      const l = screen.getAllByRole('link').find((a) => /\/events\/\d+$/.test(a.getAttribute('href') || '') && /E2E camera/.test(a.textContent));
      if (!l) throw new Error('no event yet');
      return l;
    }, { timeout: 40000, interval: 1000 });
    ids.event = link.getAttribute('href').split('/').pop();
    expect(link.textContent).toMatch(/Accident/);
  });

  it('event page: clip player, review, drafts, edit, dry-run send', async () => {
    open(`/events/${ids.event}`);
    // wait until the clip is finished (backend finalizes it after the post-roll)
    const video = await waitFor(() => {
      const v = document.querySelector('video');
      if (!v) throw new Error('clip not ready');
      return v;
    }, { timeout: 60000, interval: 1000 });
    expect(video.getAttribute('src')).toContain(`/api/events/${ids.event}/clip`);
    expect(document.querySelector('.map')).toBeTruthy();

    fireEvent.click(await screen.findByText('Confirm real event', {}, { timeout: 30000 }));
    expect(await screen.findByText('Alerts to authorities', {}, { timeout: 15000 })).toBeTruthy();
    const subjects = await waitFor(() => {
      const s = screen.getAllByLabelText('Subject');
      if (s.length < 2) throw new Error('drafts missing');
      return s;
    }, { timeout: 15000 });
    expect(subjects.length).toBe(2);                       // accident -> police + hospital

    fireEvent.change(subjects[0], { target: { value: 'EDITED SUBJECT' } });
    const sendButtons = screen.getAllByText('Send', { selector: 'button' });
    fireEvent.click(sendButtons[0]);
    await waitFor(() => expect(screen.getByText('Saved (dry-run, not sent)')).toBeTruthy(), { timeout: 15000 });
    const saved = await (await fetch(`${API}/api/events/${ids.event}/alerts`)).json();
    expect(saved.some((a) => a.subject === 'EDITED SUBJECT' && a.status === 'dry_run')).toBe(true);
  });

  it('cameras, authorities and training pages render', async () => {
    open('/cameras');
    expect(await screen.findByText('E2E camera')).toBeTruthy();
    expect(screen.getByText('Analyze an uploaded video')).toBeTruthy();
    open('/authorities');
    expect(await screen.findByText('Test Police')).toBeTruthy();
    open('/training');
    expect(await screen.findByText('Export reviewed clips')).toBeTruthy();
    await waitFor(() => expect(within(document.body).getByText('Confirmed')).toBeTruthy());
  });

  it('live push: a brand-new event shows a toast without reloading', async () => {
    open('/');
    await waitFor(() => expect(document.querySelector('.dot.on')).toBeTruthy(), { timeout: 15000 });   // websocket connected
    await fetch(API + '/api/cameras', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: 'E2E toast cam', source: VIDEO, lat: 28.6, lng: 77.2, loop: false, realtime: false, enabled: true }) });
    expect(await screen.findByText(/New Accident/, {}, { timeout: 40000 })).toBeTruthy();
  });
});
