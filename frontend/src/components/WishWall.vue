<template>
  <div class="wish-wall">
    <h3>🎓 毕业寄语墙</h3>
    <div class="wish-add">
      <div class="anon-toggle">
        <label><input type="checkbox" v-model="isAnonymous"> 匿名发送</label>
      </div>
      <textarea v-model="content" placeholder="写下你想对同学说的话..." rows="6" class="input" style="width:85ch;max-width:100%"></textarea>
      <div class="btn-bottom-right">
        <button class="btn-sm btn-primary" @click="addWish" :disabled="!content.trim()">💌 发送寄语</button>
      </div>
    </div>
    <div class="wish-grid" v-if="wishes.length">
      <div class="wish-card" v-for="w in wishes" :key="w.id" :style="{ borderLeftColor: w.avatar_color }">
        <div class="wish-author">
          <span class="wish-avatar" :style="{ background: w.avatar_color }">{{ w.is_anonymous ? '?' : (w.author||'?')[0] }}</span>
          <span>{{ w.is_anonymous ? '匿名同学' : w.author }}</span>
        </div>
        <div class="wish-content">{{ w.content }}</div>
        <div class="wish-time">{{ w.created_at?.slice(0,16) }}</div>
        <button v-if="canDelete()" class="btn-sm btn-danger mt-1" @click="delWish(w.id)">删除</button>
      </div>
    </div>
    <p v-else class="empty">还没有寄语，来做第一个留下祝福的人吧 💌</p>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const props = defineProps(['isAdmin', 'currentUser'])
const wishes = ref([])
const content = ref('')
const isAnonymous = ref(false)
const API = '/api/album'

function canDelete() { return true }  // 后端鉴权

async function load() { wishes.value = await fetch(API+'/wishes',{credentials:'include'}).then(r=>r.json()) }
async function addWish() {
  if (!content.value.trim()) return
  await fetch(API+'/wishes',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({content:content.value,is_anonymous:isAnonymous.value})})
  content.value = ''; load()
}
async function delWish(id) { if(!confirm('确定删除？'))return; const r=await fetch(API+'/wishes/'+id,{method:'DELETE',credentials:'include'}).then(r=>r.json()); if(r.error) alert(r.error); else load() }
onMounted(load)
</script>

<style scoped>
.wish-wall { max-width: 700px; margin: 0 auto; padding: 20px; }
.wish-add { background: #f8f9fa; padding: 14px; border-radius: 10px; margin-bottom: 20px; }
.anon-toggle { margin-bottom: 8px; font-size: 13px; color: #666; }
.wish-grid { display: flex; flex-direction: column; gap: 12px; }
.wish-card { background: #fff; border-radius: 10px; padding: 14px 18px; border-left: 4px solid; box-shadow: 0 2px 6px rgba(0,0,0,.04); }
.wish-author { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #555; margin-bottom: 6px; }
.wish-avatar { width: 28px; height: 28px; border-radius: 50%; color: #fff; font-size: 14px; font-weight: 700; line-height: 28px; text-align: center; }
.wish-content { font-size: 16px; color: #333; line-height: 1.6; }
.wish-time { font-size: 11px; color: #bbb; margin-top: 6px; }
.empty { text-align: center; color: #999; padding: 40px; }
.btn-bottom-right { display: flex; justify-content: flex-end; margin-top: 8px; }
</style>
