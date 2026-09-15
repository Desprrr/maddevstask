import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Прокси на backend: фронтенд везде обращается по относительным путям
// /api и /ws, а кто их реально обслуживает (vite dev-сервер здесь, nginx в
// docker-compose) — деталь окружения, а не кода приложения.
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
