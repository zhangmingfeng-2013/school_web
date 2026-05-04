// API 封装
const BASE = '/api/album'
function api(path, options) {
  return fetch(BASE + path, { credentials: 'include', ...options }).then(r => r.json())
}

export const getMe = () => api('/me')
export const getImages = (cat, sort, search) => {
  let url = '/images?category=' + cat + '&sort=' + (sort || 'newest')
  if (search) url += '&search=' + encodeURIComponent(search)
  return api(url)
}
export const getImageComments = id => api('/images/' + id + '/comments')
export const addImageComment = (id, text, replyTo, replyUser) =>
  api('/images/' + id + '/comments', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, reply_to: replyTo, reply_user: replyUser })
  })

// Like
export const getLikes = id => api('/images/' + id + '/like')
export const toggleLike = (id, liked) =>
  api('/images/' + id + '/like', { method: liked ? 'DELETE' : 'POST' })

// Download
export const downloadImage = id => window.open(BASE + '/images/' + id + '/download', '_blank')

// Share
export const getShareLink = id => api('/images/' + id + '/share')
export const createShareLink = id => api('/images/' + id + '/share', { method: 'POST' })

// Upload
export const uploadImage = fd => api('/upload', { method: 'POST', body: fd, credentials: 'include' })

// Board
export const getBoardMessages = () => api('/comments')
export const addBoardMessage = text =>
  api('/comments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })

export const deleteBoardMessage = id =>
  api('/comments/' + id, { method: 'DELETE' })

// Gallery
export const getStats = () => api('/stats')
