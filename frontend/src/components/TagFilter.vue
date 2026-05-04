<template>
  <div class="tag-bar">
    <span class="tag-label">🏷️ 标签筛选：</span>
    <button class="tag-btn" :class="{ active: activeTag===null }" @click="$emit('filter', null)">全部</button>
    <button class="tag-btn" v-for="t in tags" :key="t.id"
      :class="{ active: activeTag===t.id }"
      :style="{ borderColor: t.color, color: activeTag===t.id?'#fff':'', background: activeTag===t.id?t.color:'' }"
      @click="$emit('filter', t.id)">
      {{ t.name }}
      <span class="tag-del" @click.stop="delTag(t.id)" title="删除标签">×</span>
    </button>
    <button class="tag-btn tag-add" @click="showAdd=!showAdd">+ </button>
    <div v-if="showAdd" class="tag-form">
      <input v-model="newName" placeholder="标签名" class="input-sm" @keyup.enter="addTag">
      <input type="color" v-model="newColor" class="input-color">
      <button class="btn-sm btn-primary" @click="addTag">添加</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const props = defineProps(['activeTag'])
const emit = defineEmits(['filter'])
const tags = ref([])
const showAdd = ref(false)
const newName = ref('')
const newColor = ref('#04c')

async function load() { tags.value = await fetch('/api/album/tags',{credentials:'include'}).then(r=>r.json()) }
async function addTag() {
  if (!newName.value.trim()) return
  await fetch('/api/album/tags',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({name:newName.value,color:newColor.value})})
  newName.value = ''; showAdd.value = false; load()
}
async function delTag(id) { if(!confirm('确定删除此标签？'))return; await fetch('/api/album/tags/'+id,{method:'DELETE',credentials:'include'}); load(); emit('filter',null) }
onMounted(load)
</script>

<style scoped>
.tag-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 10px 0; }
.tag-label { font-size: 14px; color: #666; white-space: nowrap; }
.tag-btn { padding: 4px 12px; border: 2px solid #ddd; border-radius: 20px; background: #fff; font-size: 13px; cursor: pointer; transition: .2s; }
.tag-btn.active { border-color: #04c; color: #fff; background: #04c; }
.tag-del { margin-left: 4px; font-weight: 700; opacity: .5; }
.tag-btn:hover .tag-del { opacity: 1; }
.tag-add { color: #999; font-weight: 700; }
.tag-form { display: flex; gap: 4px; align-items: center; }
.input-color { width: 30px; height: 28px; border: none; cursor: pointer; }
</style>
