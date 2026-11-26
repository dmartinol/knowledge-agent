import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const target = process.env.AGENT_INTERNAL_URL || 'http://127.0.0.1:8081'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/a2a': { target, changeOrigin: true },
      '/.well-known': { target, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.js'],
    include: ['src/**/*.test.{js,jsx}', 'tests/**/*.test.js'],
  },
})
