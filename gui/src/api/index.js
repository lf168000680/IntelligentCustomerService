import axios from 'axios'
import { ElMessage } from 'element-plus'

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------
const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// ---- Request interceptor ----
http.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// ---- Response interceptor ----
http.interceptors.response.use(
  (response) => {
    // Unwrap if the backend always returns { code, data, message }
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0 && body.code !== 200) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      return body.data !== undefined ? body.data : body
    }
    return body
  },
  (error) => {
    const msg =
      error.response?.data?.message ||
      error.message ||
      '网络错误，请稍后重试'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

// ===========================================================================
//  Chat
// ===========================================================================
export function sendMessage(payload) {
  return http.post('/chat/message', payload)
}

export function testPersona(personaId, payload) {
  return http.post(`/persona/${personaId}/test`, payload)
}

export function getSessions(params) {
  return http.get('/chat/sessions', { params })
}

// ===========================================================================
//  Knowledge Base
// ===========================================================================
export function listKnowledge(params) {
  return http.get('/knowledge', { params })
}

export function searchKnowledge(query, params) {
  return http.get('/knowledge/search', { params: { q: query, ...params } })
}

export function createKnowledge(payload) {
  return http.post('/knowledge', payload)
}

export function updateKnowledge(id, payload) {
  return http.put(`/knowledge/${id}`, payload)
}

export function deleteKnowledge(id) {
  return http.delete(`/knowledge/${id}`)
}

export function getReviewQueue(params) {
  return http.get('/knowledge/review-queue', { params })
}

export function approveReview(id, payload) {
  return http.post(`/knowledge/review/${id}/approve`, payload || {})
}

export function rejectReview(id, payload) {
  return http.post(`/knowledge/review/${id}/reject`, payload || {})
}

export function triggerLearning(payload) {
  return http.post('/knowledge/learn', payload || {})
}

// ===========================================================================
//  Persona
// ===========================================================================
export function listPersonas(params) {
  return http.get('/persona', { params })
}

export function getPersona(id) {
  return http.get(`/persona/${id}`)
}

export function updatePersonaFile(id, formData) {
  return http.put(`/persona/${id}/file`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function updatePersona(id, payload) {
  return http.put(`/persona/${id}`, payload)
}

export function previewPersona(id, payload) {
  return http.post(`/persona/${id}/preview`, payload || {})
}

export function compilePrompt(id, payload) {
  return http.post(`/persona/${id}/compile`, payload || {})
}

// Persona file operations (by persona name)
export function getPersonaFile(personaName, filename) {
  return http.get(`/persona/${encodeURIComponent(personaName)}/file/${encodeURIComponent(filename)}`)
}

export function savePersonaFile(personaName, filename, content) {
  return http.put(`/persona/${encodeURIComponent(personaName)}/file/${encodeURIComponent(filename)}`, { content })
}

export function compilePersona(personaName) {
  return http.get(`/persona/${encodeURIComponent(personaName)}/compile`)
}

export function testPersonaChat(personaName, message) {
  return http.post('/persona/preview', { persona_name: personaName, message })
}

// ===========================================================================
//  AI Models
// ===========================================================================
export function listModels(params) {
  return http.get('/models', { params })
}

export function addModel(payload) {
  return http.post('/models', payload)
}

export function updateModel(id, payload) {
  return http.put(`/models/${id}`, payload)
}

export function deleteModel(id) {
  return http.delete(`/models/${id}`)
}

export function testModel(id, payload) {
  return http.post(`/models/${id}/test`, payload || {})
}

export function getModelsStatus() {
  return http.get('/models/status')
}

// ===========================================================================
//  Analytics
// ===========================================================================
export function getOverview(params) {
  return http.get('/analytics/overview', { params })
}

export function getDailyStats(params) {
  return http.get('/analytics/daily', { params })
}

export function getTopIssues(params) {
  return http.get('/analytics/top-issues', { params })
}

export function getModelUsage(params) {
  return http.get('/analytics/model-usage', { params })
}

// ===========================================================================
//  System
// ===========================================================================
export function getStatus() {
  return http.get('/system/status')
}

export function startAdapter(payload) {
  return http.post('/system/adapter/start', payload || {})
}

export function stopAdapter(payload) {
  return http.post('/system/adapter/stop', payload || {})
}

export function restartAdapter(payload) {
  return http.post('/system/adapter/restart', payload || {})
}

export function testNotification(payload) {
  return http.post('/system/notification/test', payload || {})
}
