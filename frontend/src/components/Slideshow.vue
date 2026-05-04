<template>
  <div v-if="visible" class="overlay" @click.self="stop">
    <div class="slideshow-content">
      <img :src="'/static/albums/'+images[idx].filename" :key="idx">
      <div class="slide-info">
        <div class="name">{{ images[idx].name }}</div>
        <div class="counter">{{ idx+1 }} / {{ images.length }}</div>
        <div class="controls">
          <button @click.stop="prev">⏮️</button>
          <button @click.stop="togglePause">{{ paused ? '▶️' : '⏸️' }}</button>
          <button @click.stop="next">⏭️</button>
          <button @click.stop="stop">✕ 退出</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'

const props = defineProps({ images: Array, startIndex: Number })
const emit = defineEmits(['close'])
const visible = ref(true)
const idx = ref(props.startIndex || 0)
const paused = ref(false)
let timer = null

function next() { idx.value = (idx.value + 1) % props.images.length }
function prev() { idx.value = (idx.value - 1 + props.images.length) % props.images.length }
function togglePause() { paused.value = !paused.value }
function stop() { emit('close'); visible.value = false }

function startTimer() {
  clearInterval(timer)
  if (!paused.value) {
    timer = setInterval(next, 3000)
  }
}

watch(paused, () => startTimer())
startTimer()
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.overlay {
  position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:9999;
  display:flex; align-items:center; justify-content:center;
}
.slideshow-content { max-width:90vw; max-height:90vh; text-align:center; }
.slideshow-content img {
  max-width:90vw; max-height:75vh; border-radius:8px;
  box-shadow:0 4px 30px rgba(0,0,0,.5);
}
.slide-info { margin-top:16px; color:#fff; }
.name { font-size:18px; font-weight:600; }
.counter { font-size:14px; opacity:.7; margin:4px 0 10px; }
.controls { display:flex; gap:8px; justify-content:center; }
.controls button {
  background:rgba(255,255,255,.15); color:#fff; border:none;
  border-radius:8px; padding:8px 16px; font-size:16px; cursor:pointer;
}
.controls button:hover { background:rgba(255,255,255,.25); }
</style>
