<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-box modal-wide">
      <!-- Image -->
      <div class="img-box"><img :src="'/static/albums/'+image.filename"></div>
      <div class="text-muted" style="margin-bottom:8px">{{ image.uploadTime }} · {{ image.uploaderName }}</div>

      <!-- Action buttons -->
      <div class="action-bar">
        <button :class="['btn', liked?'btn-primary':'btn-default']" @click="doLike">
          {{ liked ? '❤️' : '🤍' }} {{ likeCount }}
        </button>
        <button class="btn btn-default" @click="doDownload">⬇️ 下载</button>
        <button class="btn btn-default" @click="doShare">🔗 分享</button>
      </div>

      <!-- 弹幕 -->
      <Danmaku :imageId="image.id" />

      <!-- 标签管理 -->
      <div class="tag-section">
        <div class="tag-header">
          <span class="fw-bold">🏷️ 标签</span>
        </div>
        <div class="tag-edit">
          <label v-for="t in allTags" :key="t.id" class="tag-check">
            <input type="checkbox" :value="t.id" v-model="selectedTags">
            <span :style="{background:t.color}" class="tag-dot">{{ t.name }}</span>
          </label>
        </div>
      </div>

      <!-- Comments -->
      <h4 style="margin:12px 0 6px">💬 评论 ({{ comments.length }})</h4>
      <div class="cmt-list">
        <div v-if="comments.length===0" class="text-muted center py">暂无评论 ✍️</div>
        <div v-for="c in comments" :key="c.id" class="cmt">
          <div class="cmt-head">
            <strong>{{ c.authorName||c.author }}</strong>
            <span class="text-sm">{{ c.time }}</span>
          </div>
          <div v-if="c.replyUser" class="reply-to">回复 <strong>{{ c.replyUser }}</strong></div>
          <div class="cmt-text">{{ c.text }}</div>
          <div class="cmt-actions">
            <button class="text-btn" @click="replyTo=c; replyText='@'+ (c.authorName||c.author)+' '; $nextTick(()=>{$refs.cmtInput?.focus()})">💬 回复</button>
          </div>
        </div>
      </div>

      <!-- Comment input -->
      <div class="input-row">
        <div style="flex:1">
          <div v-if="replyTo" class="reply-hint">
            回复 <strong>{{ replyTo.authorName||replyTo.author }}</strong>
            <button class="text-btn" @click="replyTo=null; replyText=''">✕ 取消</button>
          </div>
          <textarea ref="cmtInput" v-model="replyText" rows="2" placeholder="写评论... @提及某人" @keydown.ctrl.enter="submit"></textarea>
        </div>
        <button class="btn btn-primary btn-sm" style="align-self:flex-end" @click="submit">发送</button>
      </div>

      <!-- Close -->
      <div class="center mt"><button class="btn btn-sm btn-default" @click="$emit('close')">关闭</button></div>
    </div>

    <!-- Share dialog -->
    <div v-if="shareLink !== null" class="share-overlay" @click.self="shareLink=null">
      <div class="share-box">
        <h3>🔗 分享图片</h3>
        <p v-if="shareLink" class="share-link">{{ shareLink }}</p>
        <p v-else class="text-sm">点击生成分享链接</p>
        <div class="share-actions">
          <button v-if="!shareLink" class="btn btn-primary" @click="genShare">生成链接</button>
          <template v-else>
            <button class="btn btn-primary" @click="copyShare">📋 复制链接</button>
            <a :href="'https://connect.qq.com/widget/shareqq/index.html?title='+encodeURIComponent(image.name)+'&url='+encodeURIComponent(shareLink)+'&desc=毕业纪念相册'" target="_blank" class="btn" style="background:#12b7f5;color:#fff;text-decoration:none">💬 分享到QQ</a>
          </template>
          <button class="btn btn-default" @click="shareLink=null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getImageComments, addImageComment, getLikes, toggleLike, downloadImage, createShareLink, getShareLink } from '../api.js'
import Danmaku from './Danmaku.vue'

const props = defineProps({ image: Object })
const emit = defineEmits(['close', 'refresh'])
const comments = ref([])
const replyText = ref('')
const replyTo = ref(null)
const liked = ref(false)
const likeCount = ref(0)
const shareLink = ref(null)
const cmtInput = ref(null)
const isAdmin = ref(false)
const allTags = ref([])
const imageTags = ref([])
const selectedTags = ref([])

// 标签变更自动保存
let _tagInitDone = false
watch(selectedTags, () => {
  if (!_tagInitDone) { _tagInitDone = true; return }
  saveTags()
}, { deep: true })

// Like
async function doLike() {
  await toggleLike(props.image.id, liked.value)
  liked.value = !liked.value
  likeCount.value += liked.value ? 1 : -1
}

// Download
function doDownload() { downloadImage(props.image.id) }

// Share
async function doShare() {
  shareLink.value = ''
  try {
    const r = await getShareLink(props.image.id)
    if (r.link) shareLink.value = r.link
  } catch(e) {
    console.error('Share error:', e)
  }
}
async function genShare() {
  const r = await createShareLink(props.image.id)
  if (r.link) shareLink.value = r.link
  else alert(r.error || '生成失败')
}
async function copyShare() {
  try {
    await navigator.clipboard.writeText(shareLink.value)
    alert('链接已复制！')
  } catch { prompt('复制链接:', shareLink.value) }
}

// Comments
async function load() {
  try {
    const [cmts, ls] = await Promise.all([getImageComments(props.image.id), getLikes(props.image.id)])
    comments.value = Array.isArray(cmts) ? cmts : []
    liked.value = ls.liked
    likeCount.value = ls.count || 0
  } catch {}
}

async function submit() {
  const text = replyText.value.trim()
  if (!text) return
  const data = await addImageComment(props.image.id, text, replyTo.value?.id, replyTo.value?.authorName || replyTo.value?.author)
  if (data.error) return alert(data.error)
  replyText.value = ''; replyTo.value = null
  await load()
  emit('refresh')
}

onMounted(async () => {
  load()
  try {
    const me = await fetch('/api/album/me').then(r => r.json())
    isAdmin.value = me.isTeacher
  } catch(e) {}
  loadTags()
})
async function loadTags() {
  try {
    const [all, imgTags] = await Promise.all([
      fetch('/api/album/tags').then(r => r.json()),
      fetch('/api/album/images/' + props.image.id + '/tags').then(r => r.json())
    ])
    allTags.value = all
    imageTags.value = imgTags
    selectedTags.value = imgTags.map(t => t.id)
  } catch(e) {}
}
async function saveTags() {
  await fetch('/api/album/images/' + props.image.id + '/tags', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag_ids: selectedTags.value })
  })
  loadTags()
  emit('refresh')
}
</script>

<style scoped>
.img-box { background:#f8f8f8; border-radius:8px; padding:12px; text-align:center; margin-bottom:8px; }
.img-box img { max-width:100%; max-height:420px; border-radius:4px; }
.action-bar { display:flex; gap:6px; margin-bottom:10px; flex-wrap:wrap; }
.cmt-list { max-height:220px; overflow-y:auto; border:1px solid #eee; border-radius:6px; padding:2px 10px; margin-bottom:8px; }
.cmt { padding:6px 0; border-bottom:1px solid #f0f0f0; }
.cmt:last-child { border-bottom:none; }
.cmt-head { font-size:13px; }
.cmt-head strong { color:#333; }
.cmt-text { font-size:14px; color:#555; white-space:pre-wrap; margin:2px 0; }
.reply-to { font-size:12px; color:#04c; margin:1px 0; }
.cmt-actions { display:flex; gap:4px; }
.text-btn { background:none; border:none; color:#04c; cursor:pointer; font-size:12px; padding:0 4px; }
.text-btn:hover { text-decoration:underline; }
.input-row { display:flex; gap:8px; align-items:flex-end; }
.input-row textarea { flex:1; width:100%; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; resize:none; }
.input-row textarea:focus { outline:none; border-color:#04c; }
.reply-hint { font-size:12px; color:#666; padding:4px 8px; background:#f0f7ff; border-radius:4px; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center; }
.center { text-align:center; }
.py { padding:12px 0; }
.mt { margin-top:8px; }
.text-sm { font-size:12px; color:#999; }
.text-muted { color:#999; }
.fw-bold { font-weight: 700; }

/* Tags */
.tag-section { margin: 12px 0; padding: 10px; background: #f8f9fa; border-radius: 8px; }
.tag-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.tag-display { display: flex; gap: 4px; flex-wrap: wrap; }
.tag-badge { padding: 2px 10px; border-radius: 12px; color: #fff; font-size: 12px; font-weight: 600; }
.tag-edit { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.tag-check { display: flex; align-items: center; gap: 4px; cursor: pointer; font-size: 13px; }
.tag-dot { padding: 2px 10px; border-radius: 12px; color: #fff; font-size: 12px; }

/* Share overlay */
.share-overlay { position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:1000; display:flex; align-items:center; justify-content:center; }
.share-box { background:#fff; border-radius:12px; padding:24px; max-width:400px; width:90%; text-align:center; }
.share-link { background:#f5f5f5; padding:10px; border-radius:6px; font-size:13px; word-break:break-all; margin:12px 0; }
.share-actions { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; }
</style>
