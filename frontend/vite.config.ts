import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // Served from https://pedro-boudoux.github.io/pyo/ on GitHub Pages,
  // so assets must resolve under the /pyo/ subpath.
  base: '/pyo/',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
  },
})
