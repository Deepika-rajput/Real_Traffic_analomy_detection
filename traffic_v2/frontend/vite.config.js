import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server: `npm run dev` -> http://localhost:5173, proxying the API to the backend on :8000.
const backend = process.env.BACKEND_URL || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/public': backend,
      '/ws': { target: backend, ws: true },
    },
  },
  test: { environment: 'jsdom', testTimeout: 60000, hookTimeout: 60000 },
});
