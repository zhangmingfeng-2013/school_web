<template>
  <div>
    <button class="fab" @click="visible=true">+</button>
    <div v-if="visible" class="modal-overlay" @click.self="visible=false">
      <div class="modal-box modal-narrow">
        <h3 class="mb">📤 上传图片</h3>
        <div class="field">
          <label>分类</label>
          <div class="radio-group">
            <label><input type="radio" v-model="category" value="graduation"> 🎓 毕业图片</label>
            <label><input type="radio" v-model="category" value="daily"> 📷 精彩瞬间</label>
          </div>
        </div>
        <div class="field">
          <label>选择图片（可多选）</label>
          <div class="upload-zone" @click="$refs.fileInput.click()" @dragover.prevent @drop.prevent="onDrop">
            <div v-if="files.length===0">
              <div style="font-size:32px">📁</div>
              <div>点击选择多张图片或拖拽</div>
              <div class="text-sm mt">jpg/png/gif/webp · ≤ 5MB/张</div>
            </div>
            <div v-else class="preview-list">
              <div v-for="(f, i) in files" :key="i" class="preview-item">
                <img :src="f.data">
                <button class="remove-btn" @click="files.splice(i,1)">✕</button>
              </div>
            </div>
          </div>
          <input ref="fileInput" type="file" multiple accept="image/jpeg,image/png,image/gif,image/webp" @change="onFiles" style="display:none">
        </div>
        <div class="field" v-if="files.length>0">
          <label>统一名称 <small class="text-sm">(可选，不填则用原文件名)</small></label>
          <input v-model="name" placeholder="批量命名，例如：毕业照">
        </div>
        <div class="actions">
          <span v-if="uploaded>0" class="text-sm" style="color:#04c">已上传 {{ uploaded }} 张</span>
          <span class="text-sm" v-else>{{ files.length }} 张待上传</span>
          <button class="btn btn-default" @click="visible=false;files=[]">取消</button>
          <button class="btn btn-primary" :disabled="uploading||files.length===0" @click="doUpload">
            {{ uploading ? '上传中 '+progress+'/'+files.length+'...' : '上传 '+files.length+' 张' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { uploadImage } from '../api.js'

const emit = defineEmits(['uploaded'])
const visible = ref(false)
const category = ref('graduation')
const name = ref('')
const files = ref([])
const uploading = ref(false)
const progress = ref(0)
const uploaded = ref(0)

function onFiles(e) {
  const selected = Array.from(e.target.files)
  for (const f of selected) {
    if (f.size > 5*1024*1024) { alert(f.name + ' 超过5MB，已跳过'); continue }
    if (!['image/jpeg','image/png','image/gif','image/webp'].includes(f.type)) { alert(f.name + ' 格式不支持，已跳过'); continue }
    const idx = files.value.length
    files.value.push({ file: f, data: '' })
    const r = new FileReader()
    r.onload = ev => { files.value[idx].data = ev.target.result }
    r.readAsDataURL(f)
  }
  e.target.value = ''
}

function onDrop(e) {
  const dt = e.dataTransfer
  const input = $refs?.fileInput
  if (input) { input.files = dt.files; onFiles({ target: input }) }
}

async function doUpload() {
  uploading.value = true; progress.value = 0; uploaded.value = 0
  for (const f of files.value) {
    const fd = new FormData()
    fd.append('image', f.file)
    fd.append('category', category.value)
    fd.append('name', name.value ? (name.value + (files.value.length>1 ? '_' + (progress.value+1) : '')) : f.file.name)
    const r = await uploadImage(fd)
    if (!r.error) uploaded.value++
    progress.value++
  }
  uploading.value = false
  if (uploaded.value > 0) {
    visible.value = false
    files.value = []
    name.value = ''
    emit('uploaded', category.value)
  }
}
</script>

<style scoped>
.mb { margin-bottom:14px; }
.field { margin-bottom:12px; }
.field label { font-size:13px; font-weight:600; display:block; margin-bottom:4px; }
.field input[type=text] { width:100%; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; }
.field input:focus { outline:none; border-color:#04c; }
.actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; align-items:center; }
.text-sm { font-size:12px; color:#999; }
.mt { margin-top:4px; }
.preview-list { display:flex; flex-wrap:wrap; gap:6px; }
.preview-item { position:relative; width:70px; height:70px; }
.preview-item img { width:100%; height:100%; object-fit:cover; border-radius:4px; }
.remove-btn { position:absolute; top:-6px; right:-6px; width:18px; height:18px; border-radius:50%; background:#ff4444; color:#fff; border:none; cursor:pointer; font-size:11px; line-height:18px; text-align:center; }
</style>
