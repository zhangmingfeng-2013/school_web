<template>
  <div class="playlist">
    <h3>🎵 毕业歌单</h3>
    <div class="pl-add">
      <input v-model="form.title" placeholder="歌曲名 *" class="input">
      <input v-model="form.artist" placeholder="歌手" class="input">
      <input v-model="form.url" placeholder="链接（可选）" class="input">
      <button class="btn-sm btn-primary" @click="addSong" :disabled="!form.title.trim()">+ 添加歌曲</button>
    </div>
    <div class="pl-list" v-if="songs.length">
      <div class="pl-item" v-for="s in songs" :key="s.id">
        <div class="pl-info">
          <div class="pl-title">{{ s.title }}</div>
          <div class="pl-artist" v-if="s.artist">{{ s.artist }}</div>
        </div>
        <div class="pl-actions">
          <button class="vote-btn" @click="vote(s.id)">👍 {{ s.votes }}</button>
          <button v-if="s.url" class="btn-sm btn-link" @click="window.open(s.url,'_blank')">▶️</button>
          <button v-if="isAdmin" class="btn-sm btn-danger" @click="delSong(s.id)">✕</button>
        </div>
      </div>
    </div>
    <p v-else class="empty">歌单还是空的，快来添加你喜欢的毕业歌曲 🎶</p>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const props = defineProps(['isAdmin'])
const songs = ref([])
const form = ref({ title: '', artist: '', url: '' })

async function load() {
  songs.value = await fetch('/api/album/playlist', { credentials: 'include' }).then(r => r.json())
}
async function addSong() {
  if (!form.value.title.trim()) return
  await fetch('/api/album/playlist', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(form.value)
  })
  form.value = { title: '', artist: '', url: '' }
  load()
}
async function vote(id) {
  await fetch('/api/album/playlist/' + id + '/vote', { method: 'POST', credentials: 'include' })
  load()
}
async function delSong(id) {
  if (!confirm('确定删除？')) return
  await fetch('/api/album/playlist/' + id, { method: 'DELETE', credentials: 'include' })
  load()
}
onMounted(load)
</script>

<style scoped>
.playlist { max-width: 600px; margin: 0 auto; padding: 20px; }
.pl-add { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.pl-add .input { flex: 1; min-width: 120px; padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 14px; }
.pl-list { display: flex; flex-direction: column; gap: 8px; }
.pl-item { display: flex; justify-content: space-between; align-items: center; background: #fff; border-radius: 10px; padding: 12px 16px; box-shadow: 0 2px 6px rgba(0,0,0,.04); }
.pl-title { font-weight: 700; font-size: 16px; color: #333; }
.pl-artist { font-size: 13px; color: #999; }
.pl-actions { display: flex; align-items: center; gap: 6px; }
.vote-btn { padding: 4px 12px; border: 1px solid #e0e0e0; border-radius: 20px; background: #fff; cursor: pointer; font-size: 13px; transition: .2s; }
.vote-btn:hover { background: #f0f0f0; transform: scale(1.1); }
.empty { text-align: center; color: #999; padding: 40px; }
</style>
