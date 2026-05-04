<template>
  <div>
    <div class="input-box">
      <textarea v-model="text" rows="2" placeholder="写下对大家说的话..."></textarea>
      <button class="btn btn-primary" @click="submit">发表</button>
    </div>
    <div v-if="loading" class="center"><div class="spinner"></div></div>
    <div v-else-if="messages.length===0" class="empty">
      <div class="icon">💭</div><p>还没有留言</p>
    </div>
    <div v-for="msg in messages" :key="msg.id" class="msg">
      <div class="avatar">{{ (msg.authorName||msg.author).charAt(0) }}</div>
      <div class="body">
        <div class="name">{{ msg.authorName||msg.author }}</div>
        <div class="time">{{ msg.time }}</div>
        <div class="text">{{ msg.text }}</div>
        <button v-if="canDelete(msg)" class="btn-sm btn-danger mt-1" @click="delMsg(msg.id)" style="font-size:11px;padding:2px 8px">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getBoardMessages, addBoardMessage, deleteBoardMessage } from '../api.js'

const messages = ref([])
const text = ref('')
const loading = ref(true)
const currentUser = ref('')
const isAdmin = ref(false)

async function load() {
  loading.value = true
  try { const d = await getBoardMessages(); messages.value = Array.isArray(d)?d:[] } catch {}
  loading.value = false
}

async function submit() {
  if (!text.value.trim()) return alert('请输入留言')
  const r = await addBoardMessage(text.value.trim())
  if (r.error) return alert(r.error)
  text.value = ''
  await load()
}

async function delMsg(id) {
  if (!confirm('确定删除？')) return
  const r = await deleteBoardMessage(id)
  if (r.error) return alert(r.error)
  await load()
}

function canDelete(msg) {
  return isAdmin.value || msg.author === currentUser.value
}

onMounted(async () => {
  load()
  try {
    const me = await fetch('/api/album/me', { credentials: 'include' }).then(r => r.json())
    currentUser.value = me.username
    isAdmin.value = me.isTeacher
  } catch(e) {}
})
</script>

<style scoped>
.input-box { background:#fff; border-radius:10px; padding:14px; margin-bottom:12px; display:flex; gap:8px; }
.input-box textarea { flex:1; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; resize:none; }
.input-box textarea:focus { border-color:#04c; }
.msg { background:#fff; border-radius:10px; padding:16px; margin-bottom:10px; display:flex; gap:10px; }
.avatar { width:36px; height:36px; border-radius:50%; background:#04c; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; flex-shrink:0; }
.body { flex:1; }
.name { font-weight:600; font-size:13px; }
.time { font-size:11px; color:#999; margin:2px 0 4px; }
.text { font-size:14px; color:#555; line-height:1.7; white-space:pre-wrap; word-break:break-word; }
.center { text-align:center; padding:60px; }
</style>
