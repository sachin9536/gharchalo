import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser talks to /api/*; Vite forwards it to FastAPI (no CORS needed).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_URL ?? 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
