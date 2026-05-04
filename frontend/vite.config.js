import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5800',
        changeOrigin: true
      },
      '/static/albums': {
        target: 'http://localhost:5800',
        changeOrigin: true
      }
    }
  }
})
