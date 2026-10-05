import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { wsUrl } from './api.js';

const Ctx = createContext({ connected: false, subscribe: () => () => {} });

/** One shared WebSocket to /ws/events with auto-reconnect. */
export function LiveProvider({ children }) {
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Set());

  useEffect(() => {
    let ws, timer, closed = false;
    const connect = () => {
      try { ws = new WebSocket(wsUrl('/ws/events')); } catch { timer = setTimeout(connect, 3000); return; }
      ws.onopen = () => setConnected(true);
      ws.onmessage = (m) => {
        try { const d = JSON.parse(m.data); listeners.current.forEach((f) => f(d)); } catch { /* ignore */ }
      };
      ws.onclose = () => { setConnected(false); if (!closed) timer = setTimeout(connect, 2000); };
      ws.onerror = () => ws.close();
    };
    connect();
    const ping = setInterval(() => { if (ws && ws.readyState === 1) ws.send('ping'); }, 25000);
    return () => { closed = true; clearTimeout(timer); clearInterval(ping); if (ws) ws.close(); };
  }, []);

  const subscribe = useCallback((fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn); }, []);
  return <Ctx.Provider value={{ connected, subscribe }}>{children}</Ctx.Provider>;
}

export const useLive = () => useContext(Ctx);

/** Call handler({type:'event', action:'created'|'updated', event}) for every live message. */
export function useLiveEvents(handler) {
  const { subscribe } = useLive();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((d) => ref.current(d)), [subscribe]);
}
