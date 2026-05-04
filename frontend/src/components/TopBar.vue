<template>
  <header>
    <div class="logo">🎓 毕业纪念相册 <span class="tag">Vue3</span></div>
    <div class="user" v-if="me">
      <span>{{ me.username }}</span>
      <span :class="me.isTeacher?'badge-teacher':'badge-student'">{{ me.isTeacher?'老师':'学生' }}</span>
      <a href="/dashboard" class="btn btn-sm btn-default">← 返回</a>
    </div>
    <div class="user" v-else>
      <a href="http://localhost:5800/" class="btn btn-sm btn-primary">🔐 去登录</a>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const me = ref(null)

onMounted(async () => {
  try {
    const r = await fetch('/api/album/me', { credentials: 'include' })
    if (r.ok) {
      me.value = await r.json()
      // 暴露到全局供其他组件使用
      window.__user = me.value
      // 重新分发事件让其他组件知道用户已加载
      window.dispatchEvent(new Event('user-loaded'))
    }
  } catch {}
})
</script>

<style scoped>
header { background:#fff; border-bottom:1px solid #e8e8e8; padding:14px 20px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:100; }
.logo { font-size:18px; font-weight:700; }
.logo .tag { font-size:10px; background:#04c; color:#fff; padding:1px 6px; border-radius:4px; margin-left:6px; vertical-align:middle; }
.user { font-size:13px; color:#666; display:flex; align-items:center; gap:8px; }
.badge-teacher { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; background:#fff3cd; color:#856404; }
.badge-student { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; background:#e2f0ff; color:#0056b3; }
</style>
