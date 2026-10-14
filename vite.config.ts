import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  return {
    root: '.',
    plugins: [react()],
    publicDir: 'public',
    server: {
      host: '0.0.0.0',
      proxy: { '/api': { target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
    },
    build: { outDir: 'frontend/dist', emptyOutDir: true },
    test: { environment: 'jsdom', setupFiles: './frontend/tests/setup.ts' },
  };
});
