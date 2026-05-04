<template>
  <div v-if="loading" class="center"><div class="spinner"></div></div>
  <template v-else>
    <div v-if="images.length===0" class="empty">
      <div class="icon">{{ props.category==='graduation'?'🎓':'📷' }}</div>
      <p v-if="search">没有找到相关图片</p>
      <p v-else>还没有{{ props.category==='graduation'?'毕业图片':'精彩瞬间' }}</p>
    </div>
    <div v-else class="grid">
      <div v-for="img in images" :key="img.id" class="card">
        <div class="img-wrap" @click="selectedImage=img"><img :src="'/static/albums/'+img.filename" :alt="img.name" loading="lazy"></div>
        <div class="info">
          <div class="name">{{ img.name }}</div>
          <div class="meta">
            <span>{{ img.likeCount||0 }} ♥ {{ img.commentCount||0 }} 💬</span>
            <span>{{ img.uploadTime }}</span>
          </div>
          <div class="actions">
            <button class="btn-icon" title="查看" @click="selectedImage=img">👁️</button>
            <button v-if="isTeacher" class="btn-icon" title="重命名" @click="startRename(img)">✏️</button>
            <button v-if="isTeacher" class="btn-icon danger" title="删除" @click="remove(img)">🗑️</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Rename -->
    <div v-if="renameTarget" class="modal-overlay" @click.self="renameTarget=null">
      <div class="modal-box modal-narrow">
        <h3>✏️ 重命名</h3>
        <input v-model="renameText" class="input" @keydown.enter="doRename" style="margin:12px 0;width:100%">
        <div class="flex-end">
          <button class="btn btn-default" @click="renameTarget=null">取消</button>
          <button class="btn btn-primary" :disabled="!renameText.trim()" @click="doRename">保存</button>
        </div>
      </div>
    </div>

    <ImageDetailModal v-if="selectedImage" :image="selectedImage" @close="selectedImage=null" @refresh="loadImages" />
  </template>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import ImageDetailModal from './ImageDetailModal.vue'

const props = defineProps({ category: String, sort: String, search: String, tagId: Number })
const images = ref([])
const loading = ref(true)
const selectedImage = ref(null)
const renameTarget = ref(null)
const renameText = ref('')
const isTeacher = ref(false)

async function loadImages() {
  loading.value = true
  try {
    let url = '/api/album/images?category=' + props.category + '&sort=' + (props.sort || 'newest')
    if (props.search) url += '&search=' + encodeURIComponent(props.search)
    if (props.tagId) url += '&tag_id=' + props.tagId
    const r = await fetch(url, { credentials: 'include' })
    const data = await r.json()
    images.value = Array.isArray(data) ? data : []

    for (const img of images.value) {
      try {
        const [cs, ls] = await Promise.all([
          fetch('/api/album/images/' + img.id + '/comments', { credentials: 'include' }).then(r => r.json()),
          fetch('/api/album/images/' + img.id + '/like', { credentials: 'include' }).then(r => r.json())
        ])
        img.commentCount = Array.isArray(cs) ? cs.length : 0
        img.likeCount = ls.count || 0
      } catch { img.commentCount = 0; img.likeCount = 0 }
    }
  } catch {}
  loading.value = false
}

function startRename(img) { renameTarget.value = img; renameText.value = img.name }
async function doRename() {
  if (!renameText.value.trim()) return
  const r = await fetch('/api/album/images/' + renameTarget.value.id, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: renameText.value.trim() }),
    credentials: 'include'
  }).then(r => r.json())
  if (r.error) return alert(r.error)
  renameTarget.value = null
  loadImages()
}
async function remove(img) {
  if (!confirm('删除「' + img.name + '」？评论和点赞也将一并删除。')) return
  const r = await fetch('/api/album/images/' + img.id, { method: 'DELETE', credentials: 'include' }).then(r => r.json())
  if (r.error) return alert(r.error)
  loadImages()
}

watch(() => [props.category, props.sort, props.search], loadImages)
onMounted(async () => {
  if (window.__user) isTeacher.value = window.__user.isTeacher
  else {
    try { const u = await fetch('/api/album/me', { credentials: 'include' }).then(r => r.json()); isTeacher.value = u.isTeacher } catch {}
  }
  loadImages()
})
defineExpose({ loadImages })
</script>

<style scoped>
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }
.card { background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.06); cursor:pointer; transition:.2s; }
.card:hover { transform:translateY(-2px); box-shadow:0 4px 16px rgba(0,0,0,.1); }
.img-wrap { height:170px; overflow:hidden; background:#f0f0f0; }
.img-wrap img { width:100%; height:100%; object-fit:cover; }
.info { padding:8px 10px; }
.name { font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.meta { font-size:11px; color:#999; display:flex; justify-content:space-between; margin-top:2px; }
.actions { display:none; gap:4px; margin-top:6px; }
.card:hover .actions { display:flex; }
.btn-icon { cursor:pointer; background:#f5f5f5; border:none; border-radius:4px; padding:2px 6px; font-size:13px; }
.btn-icon:hover { background:#e8e8e8; }
.btn-icon.danger:hover { background:#fee; }
.center { text-align:center; padding:60px; }
h3 { margin:0 0 4px; }
.input { padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; }
.input:focus { outline:none; border-color:#04c; }
.flex-end { display:flex; justify-content:flex-end; gap:8px; }
</style>
