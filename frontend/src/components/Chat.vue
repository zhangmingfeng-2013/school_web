<template>
  <div class="chat-app">
    <!-- Sidebar -->
    <div class="chat-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-header">
        <h5>💬 聊天</h5>
        <button class="btn-sm btn-primary" @click="sidebarOpen=false" style="display:none">✕</button>
      </div>
      <button class="channel-btn" :class="{ active: channel==='world' }" @click="switchChannel('world')">🌍 世界频道</button>
      <div class="sidebar-section">
        <div class="section-title">好友 <button class="btn-sm" @click="showSearch=!showSearch" style="font-size:11px">🔍</button></div>
        <div v-if="showSearch" class="search-box">
          <input v-model="searchQ" placeholder="搜索昵称..." class="input-sm" @keyup.enter="doSearch">
          <div v-if="searchResults.length" class="search-results">
            <div v-for="r in searchResults" :key="r.username" class="search-item" @click="addFriend(r.username)">
              {{ r.nickname }} <small>({{ r.username }})</small>
            </div>
          </div>
        </div>
        <div v-if="friendRequests.length" class="section-label">好友请求</div>
        <div v-for="r in friendRequests" :key="r.from" class="request-item">
          <span>{{ r.nickname }}</span>
          <div>
            <button class="btn-sm btn-primary" @click="acceptFriend(r.from)" style="font-size:11px;padding:2px 6px">✓</button>
            <button class="btn-sm btn-danger" @click="removeFriend(r.from)" style="font-size:11px;padding:2px 6px">✕</button>
          </div>
        </div>
        <div v-for="f in friends" :key="f.username" class="friend-item" :class="{ active: channel==='dm' && dmUser===f.username }" @click="switchDM(f.username)">
          {{ f.nickname }} <small>({{ f.username }})</small>
        </div>
      </div>
    </div>

    <!-- Chat area -->
    <div class="chat-main">
      <div class="chat-header">
        <button class="menu-btn" @click="sidebarOpen=!sidebarOpen">☰</button>
        <span>{{ channel==='world' ? '🌍 世界频道' : ('💬 ' + dmUser) }}</span>
      </div>
      <div class="chat-messages" ref="msgBox">
        <div v-if="messages.length===0" class="empty-chat">暂无消息，开始聊天吧！</div>
        <div v-for="m in messages" :key="m.id" class="chat-msg" :class="{ mine: m.sender===currentUser, recalled: m.content==='[消息已撤回]' }" @contextmenu="onContextMenu($event, m)">
          <div class="msg-sender">{{ m.sender }}</div>
          <div class="msg-bubble">{{ m.content }}</div>
          <div class="msg-time">{{ m.created_at?.slice(5,16) }}</div>
        </div>
      </div>
      <div class="chat-input">
        <input v-model="text" :placeholder="channel==='world'?'发消息到世界频道...':'发私信...'" @keyup.enter="send" maxlength="1000">
        <button class="btn-sm btn-primary" @click="send">发送</button>
      </div>
    </div>

    <!-- 右键菜单 -->
    <div v-if="contextMenu.show" class="context-menu" :style="{ left: contextMenu.x+'px', top: contextMenu.y+'px' }" @mouseleave="hideMenu">
      <div class="menu-item" @click="recallMsg(contextMenu.msgId)">↩️ 撤回消息</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'

const channel = ref('world')
const dmUser = ref('')
const messages = ref([])
const text = ref('')
const currentUser = ref('')
const friends = ref([])
const friendRequests = ref([])
const searchQ = ref('')
const searchResults = ref([])
const showSearch = ref(false)
const sidebarOpen = ref(true)
const msgBox = ref(null)
let pollTimer = null

const API = '/api/chat'

async function loadMessages() {
  let url = API + '/messages?channel=' + channel.value
  if (channel.value === 'dm') url += '&with=' + dmUser.value
  messages.value = await fetch(url, { credentials: 'include' }).then(r => r.json())
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}

async function send() {
  if (!text.value.trim()) return
  const body = { channel: channel.value, content: text.value }
  if (channel.value === 'dm') body.recipient = dmUser.value
  await fetch(API + '/send', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include', body: JSON.stringify(body)
  })
  text.value = ''
  loadMessages()
}

async function loadFriends() {
  const [fs, frs] = await Promise.all([
    fetch(API + '/friends', { credentials: 'include' }).then(r => r.json()),
    fetch(API + '/friends/requests', { credentials: 'include' }).then(r => r.json())
  ])
  friends.value = fs; friendRequests.value = frs
}

async function doSearch() {
  if (!searchQ.value.trim()) return
  searchResults.value = await fetch(API + '/search?q=' + encodeURIComponent(searchQ.value), { credentials: 'include' }).then(r => r.json())
}

async function addFriend(username) {
  const r = await fetch(API + '/friends/request', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include', body: JSON.stringify({ username })
  }).then(r => r.json())
  if (r.error) alert(r.error); else alert('好友请求已发送')
  searchResults.value = []; searchQ.value = ''
}

async function acceptFriend(username) {
  await fetch(API + '/friends/accept', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include', body: JSON.stringify({ username })
  })
  loadFriends()
}

async function removeFriend(username) {
  await fetch(API + '/friends/remove', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'include', body: JSON.stringify({ username })
  })
  loadFriends()
}

// 右键菜单
const contextMenu = ref({ show: false, x: 0, y: 0, msgId: null, msgSender: '' })

function onContextMenu(e, m) {
  if (m.content === '[消息已撤回]') return
  if (m.sender !== currentUser.value) return
  e.preventDefault()
  contextMenu.value = { show: true, x: e.clientX, y: e.clientY, msgId: m.id, msgSender: m.sender }
}
function hideMenu() { contextMenu.value.show = false }

async function recallMsg(mid) {
  if (!confirm('确定撤回这条消息？')) return
  await fetch(API + '/messages/' + mid, { method: 'DELETE', credentials: 'include' })
  hideMenu()
  loadMessages()
}

function switchChannel(ch) { channel.value = ch; dmUser.value = ''; loadMessages() }
function switchDM(user) { channel.value = 'dm'; dmUser.value = user; loadMessages() }

onMounted(async () => {
  const me = await fetch('/api/album/me', { credentials: 'include' }).then(r => r.json())
  currentUser.value = me.username
  loadMessages(); loadFriends()
  pollTimer = setInterval(() => { loadMessages(); loadFriends() }, 3000)
})
onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.chat-app { display: flex; height: calc(100vh - 150px); min-height: 500px; border: 1px solid #e0e0e0; border-radius: 10px; overflow: hidden; background: #fff; }
.chat-sidebar { width: 220px; background: #f8f9fa; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; flex-shrink: 0; }
.sidebar-header { padding: 12px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
.channel-btn { padding: 10px 12px; background: none; border: none; text-align: left; cursor: pointer; font-size: 14px; border-bottom: 1px solid #eee; }
.channel-btn.active, .channel-btn:hover { background: #e8eeff; }
.sidebar-section { flex: 1; overflow-y: auto; padding: 8px; }
.section-title { font-size: 12px; color: #999; padding: 4px 8px; display: flex; justify-content: space-between; align-items: center; }
.friend-item { padding: 6px 8px; cursor: pointer; border-radius: 6px; font-size: 13px; }
.friend-item:hover, .friend-item.active { background: #e8eeff; }
.section-label { font-size: 11px; color: #f60; padding: 4px 8px; margin-top: 4px; }
.request-item { display: flex; justify-content: space-between; align-items: center; padding: 4px 8px; font-size: 13px; }
.search-box { padding: 4px 8px; position: relative; }
.search-box .input-sm { width: 100%; padding: 6px; border: 1px solid #d9d9d9; border-radius: 4px; font-size: 13px; }
.search-results { position: absolute; top: 100%; left: 8px; right: 8px; background: #fff; border: 1px solid #e0e0e0; border-radius: 6px; z-index: 10; max-height: 150px; overflow-y: auto; }
.search-item { padding: 6px 8px; cursor: pointer; font-size: 13px; }
.search-item:hover { background: #e8eeff; }

.chat-main { flex: 1; display: flex; flex-direction: column; }
.chat-header { padding: 10px 14px; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; gap: 10px; font-weight: 700; }
.menu-btn { background: none; border: none; font-size: 18px; cursor: pointer; display: none; }
.chat-messages { flex: 1; overflow-y: auto; padding: 14px; }
.empty-chat { text-align: center; color: #999; padding: 40px; }
.chat-msg { margin-bottom: 12px; max-width: 70%; }
.chat-msg.mine { margin-left: auto; }
.msg-sender { font-size: 11px; color: #999; margin-bottom: 2px; }
.chat-msg.mine .msg-sender { text-align: right; }
.msg-bubble { padding: 8px 14px; border-radius: 14px; background: #f0f0f0; font-size: 14px; line-height: 1.5; word-break: break-word; }
.chat-msg.mine .msg-bubble { background: #04c; color: #fff; }
.msg-time { font-size: 10px; color: #bbb; margin-top: 2px; }
.chat-msg.mine .msg-time { text-align: right; }
.chat-msg.recalled .msg-bubble { background: #f5f5f5; color: #999; font-style: italic; }
.chat-input { display: flex; gap: 8px; padding: 10px 14px; border-top: 1px solid #e0e0e0; }
.chat-input input { flex: 1; padding: 8px 14px; border: 1px solid #d9d9d9; border-radius: 20px; font-size: 14px; }
.chat-input input:focus { border-color: #04c; }

@media (max-width: 768px) {
  .chat-sidebar { position: absolute; top: 0; left: 0; bottom: 0; z-index: 10; transform: translateX(-100%); transition: .2s; }
  .chat-sidebar.open { transform: translateX(0); }
  .menu-btn { display: block; }
  .chat-app { position: relative; }
}

.context-menu { position: fixed; background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,.15); z-index: 1000; min-width: 120px; }
.menu-item { padding: 8px 16px; cursor: pointer; font-size: 13px; }
.menu-item:hover { background: #f0f0f0; }
</style>
