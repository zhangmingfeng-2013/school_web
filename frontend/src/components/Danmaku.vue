<template>
  <div class="danmaku-overlay" ref="container">
    <div class="danmaku-input">
      <input v-model="text" placeholder="发一条弹幕吧..." @keyup.enter="send" maxlength="200" class="dm-input">
      <input type="color" v-model="color" class="dm-color" title="颜色">
      <button class="btn-sm btn-primary" @click="send" :disabled="!text.trim()">发送</button>
    </div>
    <div class="danmaku-stage" ref="stage">
      <span class="dm-item" v-for="dm in activeDanmaku" :key="dm.key"
        :style="{ color: dm.color, top: dm.top + '%', animationDuration: dm.duration + 's' }"
        @animationend="removeItem(dm.key)">
        {{ dm.text }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
const props = defineProps(['imageId'])
const text = ref('')
const color = ref('#fff')
const activeDanmaku = ref([])
const allDanmaku = ref([])
let keyCounter = 0
let pollTimer = null

async function load() {
  if (!props.imageId) return
  const data = await fetch('/api/album/images/' + props.imageId + '/danmaku').then(r => r.json())
  allDanmaku.value = data
  // Replay existing
  activeDanmaku.value = []
  data.forEach(d => emitDanmaku(d))
}
function emitDanmaku(dm) {
  const top = Math.random() * 85 + 5
  const duration = 6 + Math.random() * 4
  activeDanmaku.value.push({
    key: keyCounter++,
    text: dm.text,
    color: dm.color,
    top,
    duration
  })
}
function removeItem(key) {
  activeDanmaku.value = activeDanmaku.value.filter(d => d.key !== key)
}
async function send() {
  if (!text.value.trim() || !props.imageId) return
  await fetch('/api/album/images/' + props.imageId + '/danmaku', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text.value, color: color.value, position: 50 })
  })
  emitDanmaku({ text: text.value, color: color.value })
  text.value = ''
  allDanmaku.value.push({ text: text.value, color: color.value })
}
onMounted(() => {
  load()
  // Auto-poll new danmaku
  pollTimer = setInterval(async () => {
    if (!props.imageId) return
    const data = await fetch('/api/album/images/' + props.imageId + '/danmaku').then(r => r.json())
    if (data.length > allDanmaku.value.length) {
      const newOnes = data.slice(allDanmaku.value.length)
      newOnes.forEach(d => emitDanmaku(d))
      allDanmaku.value = data
    }
  }, 3000)
})
onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.danmaku-overlay { position: relative; }
.danmaku-input { display: flex; gap: 4px; margin-bottom: 10px; }
.dm-input { flex: 1; padding: 6px 10px; border: 1px solid rgba(255,255,255,.3); border-radius: 6px; background: rgba(0,0,0,.3); color: #fff; font-size: 13px; }
.dm-input::placeholder { color: rgba(255,255,255,.5); }
.dm-color { width: 32px; height: 32px; border: none; border-radius: 4px; cursor: pointer; background: none; }
.danmaku-stage { position: relative; height: 200px; overflow: hidden; background: rgba(0,0,0,.15); border-radius: 10px; }
.dm-item { position: absolute; left: 100%; white-space: nowrap; font-size: 18px; font-weight: 700; text-shadow: 1px 1px 2px rgba(0,0,0,.8); animation: dm-scroll linear forwards; pointer-events: none; }
@keyframes dm-scroll {
  from { left: 100%; }
  to { left: -100%; }
}
</style>
