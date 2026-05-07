<template>
  <div class="classmates">
    <div class="cm-header">
      <h3>👥 同学录</h3>
      <button class="btn-sm btn-primary" @click="showForm ? resetForm() : (showForm=true)">{{ showForm?'取消':'+ 添加同学' }}</button>
    </div>
    <div v-if="showForm" class="add-form">
      <input v-model="form.name" placeholder="姓名 *" class="input">
      <input v-model="form.nickname" placeholder="昵称" class="input">
      <input v-model="form.class_name" placeholder="班级（如：1班、2班）" class="input" style="border-color:#667eea;">
      <input v-model="form.graduation_year" placeholder="届数（如：2026届）" class="input" style="border-color:#667eea;">
      <input v-model="form.email" placeholder="邮箱" class="input">
      <input v-model="form.phone" placeholder="电话" class="input">
      <input type="date" v-model="form.birthday" class="input">
      <input v-model="form.motto" placeholder="座右铭" class="input">
      <input v-model="form.interests" placeholder="兴趣爱好" class="input">
      <input v-model="form.future_plan" placeholder="未来计划" class="input">
      <button class="btn-sm btn-primary" @click="addClassmate">{{ editingId ? '更新' : '提交' }}</button>
    </div>
    <!-- 班级标签 -->
    <div class="cm-classes" v-if="classes.length">
      <button :class="{ active: activeClass === '' }" @click="activeClass=''">全部</button>
      <button v-for="cls in classes" :key="cls" :class="{ active: activeClass === cls }" @click="activeClass=cls">{{ cls }}</button>
    </div>
    <div class="cm-grid" v-if="filtered.length">
      <div class="cm-card" v-for="c in filtered" :key="c.id">
        <div class="cm-avatar">{{ c.name[0] }}</div>
        <div class="cm-name">{{ c.name }} <small v-if="c.nickname">({{ c.nickname }})</small></div>
        <div class="cm-class" v-if="c.class_name || c.graduation_year">
          <span v-if="c.graduation_year" class="cm-grad">{{ c.graduation_year }}</span>
          <span v-if="c.class_name">{{ c.class_name }}</span>
        </div>
        <div class="cm-info" v-if="c.motto">💬 {{ c.motto }}</div>
        <div class="cm-info" v-if="c.interests">❤️ {{ c.interests }}</div>
        <div class="cm-info" v-if="c.email">📧 {{ c.email }}</div>
        <div class="cm-info" v-if="c.phone">📱 {{ c.phone }}</div>
        <div class="cm-info" v-if="c.future_plan">🎯 {{ c.future_plan }}</div>
        <button v-if="currentUser===c.created_by||isAdmin" class="btn-sm btn-primary mt-2" @click="editClassmate(c)">编辑</button>
        <button v-if="isAdmin" class="btn-sm btn-danger mt-2" @click="delClassmate(c.id)">删除</button>
      </div>
    </div>
    <p v-else class="empty">还没有同学信息，快来添加吧！</p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
const props = defineProps(['isAdmin','currentUser'])
const classmates = ref([])
const showForm = ref(false)
const editingId = ref(null)
const activeClass = ref('')
const form = ref({ name: '', nickname: '', class_name: '', graduation_year: '', email: '', phone: '', birthday: '', motto: '', interests: '', future_plan: '' })

const classes = computed(() => {
  const keys = classmates.value.map(c => {
    const year = c.graduation_year || ''
    const cls = c.class_name || ''
    return year ? year + '·' + cls : cls
  }).filter(Boolean)
  return [...new Set(keys)].sort()
})
const filtered = computed(() => {
  if (!activeClass.value) return classmates.value
  return classmates.value.filter(c => {
    const year = c.graduation_year || ''
    const cls = c.class_name || ''
    const key = year ? year + '·' + cls : cls
    return key === activeClass.value
  })
})

const API = '/api/album'
async function load() { classmates.value = await fetch(API+'/classmates',{credentials:'include'}).then(r=>r.json()) }
async function addClassmate() {
  if (!form.value.name) return alert('姓名必填')
  if (editingId.value) {
    await fetch(API+'/classmates/'+editingId.value,{method:'PUT',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(form.value)})
  } else {
    await fetch(API+'/classmates',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(form.value)})
  }
  resetForm(); load()
}
function editClassmate(c) {
  form.value = { name: c.name, nickname: c.nickname||'', class_name: c.class_name||'', graduation_year: c.graduation_year||'', email: c.email||'', phone: c.phone||'', birthday: c.birthday||'', motto: c.motto||'', interests: c.interests||'', future_plan: c.future_plan||'' }
  editingId.value = c.id
  showForm.value = true
}
function resetForm() {
  form.value = { name: '', nickname: '', class_name: '', graduation_year: '', email: '', phone: '', birthday: '', motto: '', interests: '', future_plan: '' }
  editingId.value = null; showForm.value = false
}
async function delClassmate(id) { if(!confirm('确定删除？'))return; await fetch(API+'/classmates/'+id,{method:'DELETE',credentials:'include'}); load() }
onMounted(load)
</script>

<style scoped>
.classmates { max-width: 900px; margin: 0 auto; padding: 20px; }
.cm-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.cm-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.cm-card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.06); text-align: center; }
.cm-avatar { width: 56px; height: 56px; border-radius: 50%; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; font-size: 24px; font-weight: 700; line-height: 56px; margin: 0 auto 10px; }
.cm-name { font-weight: 700; font-size: 18px; color: #333; }
.cm-class { display: inline-block; margin-top: 4px; padding: 1px 10px; border-radius: 12px; background: rgba(102,126,234,.1); color: #667eea; font-size: 12px; font-weight: 600; }
.cm-grad { margin-right: 4px; background: rgba(118,75,162,.12); border-radius: 10px; padding: 0 6px; }
.cm-info { margin-top: 4px; font-size: 13px; color: #666; }
.add-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; background: #f8f9fa; padding: 14px; border-radius: 10px; max-width: 500px; }
.empty { text-align: center; color: #999; padding: 40px; }
.cm-classes { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.cm-classes button { padding: 4px 14px; border-radius: 16px; border: 1px solid #ddd; background: #fff; cursor: pointer; font-size: 13px; transition: .2s; }
.cm-classes button.active { background: #667eea; color: #fff; border-color: #667eea; }
</style>
