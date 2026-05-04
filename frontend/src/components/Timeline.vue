<template>
  <div class="timeline">
    <div class="tl-header">
      <h3>📅 班级大事记</h3>
      <button v-if="isAdmin" class="btn-sm btn-primary" @click="showForm=!showForm">{{ showForm?'取消':'+ 添加事件' }}</button>
    </div>
    <div v-if="showForm" class="add-form">
      <input v-model="form.title" placeholder="事件标题" class="input">
      <textarea v-model="form.description" placeholder="描述（可选）" class="input" rows="2"></textarea>
      <input type="date" v-model="form.event_date" class="input">
      <button class="btn-sm btn-primary" @click="addEvent">提交</button>
    </div>
    <div class="tl-list" v-if="events.length">
      <div class="tl-item" v-for="e in events" :key="e.id">
        <div class="tl-dot"></div>
        <div class="tl-card">
          <div class="tl-date">{{ e.event_date }}</div>
          <div class="tl-title">{{ e.title }}</div>
          <div class="tl-desc" v-if="e.description">{{ e.description }}</div>
          <button v-if="isAdmin" class="btn-sm btn-danger" @click="delEvent(e.id)">删除</button>
        </div>
      </div>
    </div>
    <p v-else class="empty">暂无大事记，等待添加...</p>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const props = defineProps(['isAdmin'])
const events = ref([])
const showForm = ref(false)
const form = ref({ title: '', description: '', event_date: '' })

const API = '/api/album'
async function load() {
  events.value = await fetch(API + '/events', { credentials: 'include' }).then(r => r.json())
}
async function addEvent() {
  if (!form.value.title || !form.value.event_date) return alert('标题和日期必填')
  await fetch(API + '/events', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include', body: JSON.stringify(form.value)
  })
  form.value = { title: '', description: '', event_date: '' }; showForm.value = false; load()
}
async function delEvent(id) {
  if (!confirm('确定删除？')) return
  await fetch(API + '/events/' + id, { method: 'DELETE', credentials: 'include' }); load()
}
onMounted(load)
</script>

<style scoped>
.timeline { max-width: 700px; margin: 0 auto; padding: 20px; }
.tl-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.tl-list { position: relative; padding-left: 24px; border-left: 3px solid #e0e0e0; }
.tl-item { position: relative; margin-bottom: 24px; }
.tl-dot { position: absolute; left: -33px; top: 8px; width: 14px; height: 14px; border-radius: 50%; background: #667eea; border: 3px solid #fff; box-shadow: 0 0 0 3px #667eea; }
.tl-card { background: #fff; border-radius: 10px; padding: 14px 18px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.tl-date { font-size: 12px; color: #999; margin-bottom: 4px; }
.tl-title { font-weight: 700; font-size: 16px; color: #333; }
.tl-desc { margin-top: 6px; color: #666; font-size: 14px; }
.add-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; background: #f8f9fa; padding: 14px; border-radius: 10px; }
.empty { text-align: center; color: #999; padding: 40px; }
</style>
