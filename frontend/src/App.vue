<template>
  <div>
    <TopBar />
    <div class="tabs">
      <button :class="{active:tab==='graduation'}" @click="switchTab('graduation')">🎓 毕业图片</button>
      <button :class="{active:tab==='daily'}" @click="switchTab('daily')">📷 精彩瞬间</button>
      <button :class="{active:tab==='board'}" @click="switchTab('board')">💬 留言板</button>
      <button :class="{active:tab==='timeline'}" @click="switchTab('timeline')">📅 大事记</button>
      <button :class="{active:tab==='classmates'}" @click="switchTab('classmates')">👥 同学录</button>
      <button :class="{active:tab==='wishes'}" @click="switchTab('wishes')">🎓 寄语墙</button>
      <button :class="{active:tab==='playlist'}" @click="switchTab('playlist')">🎵 歌单</button>
      <button :class="{active:tab==='stats'}" @click="switchTab('stats')">📊 统计</button>
    </div>
    <main>
      <CountDown v-if="showCountdown" @close="showCountdown=false" />

      <!-- 照片标签筛选 -->
      <TagFilter v-if="tab==='graduation'||tab==='daily'" :activeTag="activeTag" :isAdmin="isAdmin" @filter="onTagFilter" />

      <div v-if="tab!=='board'&&tab!=='timeline'&&tab!=='classmates'&&tab!=='wishes'&&tab!=='playlist'&&tab!=='stats'" class="toolbar">
        <div class="search-box">
          <input v-model="search" placeholder="搜索图片名称..." @input="triggerSearch">
          <button class="btn-sm btn-primary" @click="doSearch">🔍</button>
          <button v-if="search" class="btn-sm btn-default" @click="search='';doSearch()">✕</button>
        </div>
        <div class="sort-box">
          <label>排序：</label>
          <select v-model="sort" @change="doSearch">
            <option value="newest">最新</option>
            <option value="oldest">最早</option>
          </select>
        </div>
      </div>
      <ImageGrid v-if="tab!=='board'&&tab!=='timeline'&&tab!=='classmates'&&tab!=='wishes'&&tab!=='playlist'&&tab!=='stats'" :key="tab+sort+search+activeTag" :category="tab" :sort="sort" :search="search" :tagId="activeTag" ref="grid" />
      <MessageBoard v-else-if="tab==='board'" />
      <Timeline v-else-if="tab==='timeline'" :isAdmin="isAdmin" />
      <Classmates v-else-if="tab==='classmates'" :isAdmin="isAdmin" />
      <WishWall v-else-if="tab==='wishes'" :isAdmin="isAdmin" :currentUser="currentUser" />
      <Playlist v-else-if="tab==='playlist'" :isAdmin="isAdmin" />
      <StatsChart v-else-if="tab==='stats'" />
    </main>
    <UploadModal @uploaded="onUploaded" />
    <MusicPlayer />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import TopBar from './components/TopBar.vue'
import CountDown from './components/CountDown.vue'
import ImageGrid from './components/ImageGrid.vue'
import MessageBoard from './components/MessageBoard.vue'
import UploadModal from './components/UploadModal.vue'
import MusicPlayer from './components/MusicPlayer.vue'
import Timeline from './components/Timeline.vue'
import Classmates from './components/Classmates.vue'
import WishWall from './components/WishWall.vue'
import TagFilter from './components/TagFilter.vue'
import Playlist from './components/Playlist.vue'
import StatsChart from './components/StatsChart.vue'

const tab = ref('graduation')
const search = ref('')
const sort = ref('newest')
const grid = ref(null)
const showCountdown = ref(true)
const isAdmin = ref(false)
const currentUser = ref('')
const activeTag = ref(null)
let timer = null

function switchTab(t) { tab.value = t; search.value = ''; sort.value = 'newest'; activeTag.value = null }
function triggerSearch() { clearTimeout(timer); timer = setTimeout(doSearch, 300) }
function doSearch() { if (grid.value && (tab.value==='graduation'||tab.value==='daily')) grid.value.loadImages() }
function onUploaded(cat) { tab.value = cat; search.value = '' }
function onTagFilter(tagId) { activeTag.value = tagId; doSearch() }

onMounted(async () => {
  try {
    const me = await fetch('/api/album/me', { credentials: 'include' }).then(r => r.json())
    isAdmin.value = me.isTeacher
    currentUser.value = me.username
  } catch(e) {}
})
</script>

<style scoped>
.tabs { display:flex; background:#fff; border-bottom:1px solid #e8e8e8; overflow-x:auto; }
.tabs button { flex:0 0 auto; padding:14px 10px; background:#fff; font-size:14px; font-weight:700; color:#999; transition:.2s; cursor:pointer; border:none; letter-spacing:1px; white-space:nowrap; }
.tabs button.active { color:#04c; border-bottom:3px solid #04c; font-size:15px; }
main { max-width:1000px; margin:0 auto; padding:16px; }
.toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; flex-wrap:wrap; }
.search-box { display:flex; gap:4px; flex:1; max-width:360px; }
.search-box input { flex:1; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; }
.search-box input:focus { outline:none; border-color:#04c; }
.sort-box { display:flex; align-items:center; gap:4px; font-size:14px; color:#666; }
.sort-box select { padding:6px 8px; border:1px solid #d9d9d9; border-radius:4px; font-size:14px; }
</style>
