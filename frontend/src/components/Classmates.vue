<template>
  <div class="classmates">
    <div class="cm-header">
      <h3>👥 同学录</h3>
      <button class="btn-sm btn-primary" @click="showForm=!showForm">{{ showForm?'取消':'+ 添加同学' }}</button>
    </div>
    <div v-if="showForm" class="add-form">
      <input v-model="form.name" placeholder="姓名 *" class="input">
      <input v-model="form.nickname" placeholder="昵称" class="input">
      <input v-model="form.email" placeholder="邮箱" class="input">
      <input v-model="form.phone" placeholder="电话" class="input">
      <input type="date" v-model="form.birthday" class="input">
      <input v-model="form.motto" placeholder="座右铭" class="input">
      <input v-model="form.interests" placeholder="兴趣爱好" class="input">
      <input v-model="form.future_plan" placeholder="未来计划" class="input">
      <button class="btn-sm btn-primary" @click="addClassmate">提交</button>
    </div>
    <div class="cm-grid" v-if="classmates.length">
      <div class="cm-card" v-for="c in classmates" :key="c.id">
        <div class="cm-avatar">{{ c.name[0] }}</div>
        <div class="cm-name">{{ c.name }} <small v-if="c.nickname">({{ c.nickname }})</small></div>
        <div class="cm-info" v-if="c.motto">💬 {{ c.motto }}</div>
        <div class="cm-info" v-if="c.interests">❤️ {{ c.interests }}</div>
        <div class="cm-info" v-if="c.email">📧 {{ c.email }}</div>
        <div class="cm-info" v-if="c.phone">📱 {{ c.phone }}</div>
        <div class="cm-info" v-if="c.future_plan">🎯 {{ c.future_plan }}</div>
        <button v-if="isAdmin" class="btn-sm btn-danger mt-2" @click="delClassmate(c.id)">删除</button>
      </div>
    </div>
    <p v-else class="empty">还没有同学信息，快来添加吧！</p>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const props = defineProps(['isAdmin'])
const classmates = ref([])
const showForm = ref(false)
const form = ref({ name: '', nickname: '', email: '', phone: '', birthday: '', motto: '', interests: '', future_plan: '' })

const API = '/api/album'
async function load() { classmates.value = await fetch(API+'/classmates',{credentials:'include'}).then(r=>r.json()) }
async function addClassmate() {
  if (!form.value.name) return alert('姓名必填')
  await fetch(API+'/classmates',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(form.value)})
  form.value = { name: '', nickname: '', email: '', phone: '', birthday: '', motto: '', interests: '', future_plan: '' }; showForm.value = false; load()
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
.cm-info { margin-top: 4px; font-size: 13px; color: #666; }
.add-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; background: #f8f9fa; padding: 14px; border-radius: 10px; max-width: 500px; }
.empty { text-align: center; color: #999; padding: 40px; }
</style>
