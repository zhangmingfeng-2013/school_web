<template>
  <div class="music-bar" v-if="show">
    <button class="music-btn" @click="toggle">
      {{ playing ? '🔊' : '🔇' }}
    </button>
    <span class="music-label">背景音</span>
    <button class="music-close" @click="show=false">✕</button>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'

const show = ref(true)
const playing = ref(false)
let ctx = null
let nodes = []

// 创建舒缓环境音 — 多层正弦波叠加 + 缓慢调制
function createAmbient() {
  ctx = new (window.AudioContext || window.webkitAudioContext)()

  // 主音量
  const masterGain = ctx.createGain()
  masterGain.gain.value = 0.25
  masterGain.connect(ctx.destination)

  // 基础和弦：C大调柔和铺垫 (C3, E3, G3, C4)
  const baseFreqs = [130.81, 164.81, 196.00, 261.63]
  // 少量高八度泛音
  const highFreqs = [329.63, 392.00, 523.25]

  const allNodes = []

  // Pad 层 — 缓慢起落的基础音
  baseFreqs.forEach((freq, i) => {
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.value = freq

    const lfo = ctx.createOscillator()
    lfo.type = 'sine'
    lfo.frequency.value = 0.08 + i * 0.03 // 缓慢漂移
    const lfoGain = ctx.createGain()
    lfoGain.gain.value = 2 + i * 0.5
    lfo.connect(lfoGain)
    lfoGain.connect(osc.frequency)
    lfo.start()

    const envGain = ctx.createGain()
    envGain.gain.value = 0
    envGain.gain.setTargetAtTime(0.3, ctx.currentTime + i * 0.5, 2.0)

    osc.connect(envGain)
    envGain.connect(masterGain)
    osc.start()
    allNodes.push(osc, envGain, lfo, lfoGain)
  })

  // 高音泛音 — 非常轻柔
  highFreqs.forEach((freq, i) => {
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.value = freq

    const envGain = ctx.createGain()
    envGain.gain.value = 0
    envGain.gain.setTargetAtTime(0.08, ctx.currentTime + i * 0.7, 3.0)

    osc.connect(envGain)
    envGain.connect(masterGain)
    osc.start()
    allNodes.push(osc, envGain)
  })

  // 微风般的高频 shimmer
  const shimmer = ctx.createOscillator()
  shimmer.type = 'sine'
  shimmer.frequency.value = 800
  const shimmerLFO = ctx.createOscillator()
  shimmerLFO.type = 'triangle'
  shimmerLFO.frequency.value = 0.12
  const shimmerLFOg = ctx.createGain()
  shimmerLFOg.gain.value = 100
  shimmerLFO.connect(shimmerLFOg)
  shimmerLFOg.connect(shimmer.frequency)
  shimmerLFO.start()

  const shimmerGain = ctx.createGain()
  shimmerGain.gain.value = 0.01
  shimmer.connect(shimmerGain)
  shimmerGain.connect(masterGain)
  shimmer.start()
  allNodes.push(shimmer, shimmerGain, shimmerLFO, shimmerLFOg)

  nodes = allNodes
}

function toggle() {
  playing.value = !playing.value
  if (playing.value) {
    if (ctx && ctx.state === 'suspended') {
      ctx.resume()
    } else if (!ctx) {
      createAmbient()
    }
  } else {
    if (ctx) {
      ctx.close()
      ctx = null
      nodes = []
    }
  }
}

onUnmounted(() => {
  if (ctx) { ctx.close(); nodes = [] }
})
</script>

<style scoped>
.music-bar {
  position:fixed; bottom:90px; right:16px; z-index:90;
  display:flex; align-items:center; gap:4px;
  background:#fff; border-radius:20px; padding:6px 12px;
  box-shadow:0 2px 10px rgba(0,0,0,.12); font-size:13px;
}
.music-btn { background:none; border:none; font-size:18px; cursor:pointer; }
.music-label { color:#666; font-size:12px; }
.music-close { background:none; border:none; color:#999; cursor:pointer; font-size:12px; margin-left:4px; }
</style>
