<template>
  <div class="stats-chart">
    <h3>📊 数据统计</h3>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{{ stats.totalImages || 0 }}</div>
        <div class="stat-label">照片总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ stats.totalComments || 0 }}</div>
        <div class="stat-label">评论数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ stats.totalLikes || 0 }}</div>
        <div class="stat-label">点赞数</div>
      </div>
    </div>

    <div class="chart-section" v-if="stats.topUploaders?.length">
      <h4>📸 上传达人</h4>
      <div class="bar-chart">
        <div class="bar-row" v-for="(u,i) in stats.topUploaders" :key="i">
          <span class="bar-label">{{ u.user }}</span>
          <div class="bar-track"><div class="bar-fill" :style="{ width: barWidth(u.count, stats.topUploaders[0].count) }"></div></div>
          <span class="bar-val">{{ u.count }}</span>
        </div>
      </div>
    </div>

    <div class="chart-section" v-if="stats.topLiked?.length">
      <h4>❤️ 最受欢迎照片</h4>
      <div class="liked-list">
        <div class="liked-item" v-for="(p,i) in stats.topLiked" :key="i">
          <span class="liked-rank">#{{ i+1 }}</span>
          <span class="liked-name">{{ p.name }}</span>
          <span class="liked-count">❤️ {{ p.likes }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
const stats = ref({})

async function load() {
  stats.value = await fetch('/api/album/stats').then(r => r.json())
}
function barWidth(val, max) {
  if (!max) return '0%'
  return Math.max(5, (val/max)*100) + '%'
}
onMounted(load)
</script>

<style scoped>
.stats-chart { max-width: 700px; margin: 0 auto; padding: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px; }
.stat-card { background: #fff; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.stat-num { font-size: 32px; font-weight: 800; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.stat-label { font-size: 13px; color: #999; margin-top: 4px; }
.chart-section { background: #fff; border-radius: 12px; padding: 18px; margin-bottom: 14px; box-shadow: 0 2px 6px rgba(0,0,0,.04); }
.chart-section h4 { margin: 0 0 12px; color: #555; }
.bar-chart { display: flex; flex-direction: column; gap: 10px; }
.bar-row { display: flex; align-items: center; gap: 10px; }
.bar-label { width: 80px; font-size: 13px; color: #555; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { flex: 1; height: 20px; background: #f0f0f0; border-radius: 10px; overflow: hidden; }
.bar-fill { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); border-radius: 10px; transition: width 0.6s; }
.bar-val { font-size: 13px; color: #999; width: 30px; }
.liked-list { display: flex; flex-direction: column; gap: 8px; }
.liked-item { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.liked-rank { font-weight: 700; color: #667eea; width: 30px; }
.liked-name { flex: 1; font-size: 14px; color: #333; }
.liked-count { color: #e74c3c; font-weight: 700; }
</style>
