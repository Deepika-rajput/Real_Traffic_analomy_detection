import React, { createContext, useContext, useState } from 'react';
import { api } from './api.js';
import { usePoll } from './util.js';

const Ctx = createContext({ health: null, stats: null, offline: false, refresh: () => {} });

/** Backend health (mock/dry-run flags) + headline stats for the nav badge. */
export function HealthProvider({ children }) {
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [offline, setOffline] = useState(false);
  const [tick, setTick] = useState(0);

  usePoll(async () => {
    try {
      setHealth(await api.get('/api/health'));
      setOffline(false);
    } catch { setOffline(true); return; }
    try { setStats(await api.get('/api/stats')); } catch { /* 401 handled by the key banner */ }
  }, 5000, [tick]);

  return <Ctx.Provider value={{ health, stats, offline, refresh: () => setTick((t) => t + 1) }}>{children}</Ctx.Provider>;
}

export const useHealth = () => useContext(Ctx);
