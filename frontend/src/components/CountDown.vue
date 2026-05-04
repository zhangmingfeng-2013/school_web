<template>
  <div class="countdown">
    <div class="cd-inner">
      <div class="cd-icon">🎓</div>
      <div class="cd-text">
        <div class="cd-label">距离毕业还有</div>
        <div class="cd-time">{{ days }} 天 {{ hours }} 时 {{ minutes }} 分 {{ seconds }} 秒</div>
        <div class="cd-date">目标日期：{{ targetDate }}</div>
      </div>
      <button class="cd-close" @click="$emit('close')">✕</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const emit = defineEmits(['close'])
const targetDate = ref('2026-06-20')
const days = ref(0)
const hours = ref(0)
const minutes = ref(0)
const seconds = ref(0)
let timer = null

function calc() {
  const now = new Date()
  const end = new Date(targetDate.value + 'T23:59:59')
  const diff = Math.max(0, end - now)
  days.value = Math.floor(diff / (1000 * 60 * 60 * 24))
  hours.value = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  minutes.value = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
  seconds.value = Math.floor((diff % (1000 * 60)) / 1000)
}

function changeDate() {
  const d = prompt('设置毕业日期（YYYY-MM-DD）：', targetDate.value)
  if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) {
    targetDate.value = d
    localStorage.setItem('grad_date', d)
    calc()
  }
}

onMounted(() => {
  const saved = localStorage.getItem('grad_date')
  if (saved) targetDate.value = saved
  calc()
  timer = setInterval(calc, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.countdown { 
  background: linear-gradient(135deg, #667eea, #764ba2);
  border-radius: 12px; padding:14px 18px; margin-bottom:14px; color:#fff;
  position:relative;
}
.cd-inner { display:flex; align-items:center; gap:14px; }
.cd-icon { font-size:36px; flex-shrink:0; }
.cd-text { flex:1; }
.cd-label { font-size:12px; opacity:.8; }
.cd-time { font-size:22px; font-weight:700; letter-spacing:1px; }
.cd-date { font-size:11px; opacity:.7; cursor:pointer; }
.cd-date:hover { opacity:1; text-decoration:underline; }
.cd-close { position:absolute; top:8px; right:10px; background:none; border:none; color:#fff; opacity:.6; cursor:pointer; font-size:14px; }
.cd-close:hover { opacity:1; }
</style>
