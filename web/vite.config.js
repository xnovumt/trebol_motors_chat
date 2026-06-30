import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// En dev, /api se reenvía al servidor Python (server.py en :8000).
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
