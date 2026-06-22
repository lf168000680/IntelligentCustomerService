<template>
  <div class="live-chat">
    <div class="split-container">
      <!-- =================================================================== -->
      <!--  Left Panel — Session List                                          -->
      <!-- =================================================================== -->
      <div class="left-panel">
        <div class="panel-header">
          <span class="panel-title">活跃会话</span>
          <el-select
            v-model="platformFilter"
            size="small"
            style="width: 110px"
            placeholder="平台"
          >
            <el-option label="全部平台" value="all" />
            <el-option label="淘宝" value="taobao" />
            <el-option label="抖音" value="douyin" />
          </el-select>
        </div>

        <div class="session-list" v-loading="loading">
          <div
            v-for="s in filteredSessions"
            :key="s.id || s.sessionId"
            class="session-item"
            :class="{ active: selectedSessionId === (s.id || s.sessionId) }"
            @click="onSelectSession(s)"
          >
            <div class="session-avatar">
              <el-avatar :size="40" :icon="UserFilled" />
            </div>
            <div class="session-info">
              <div class="session-top">
                <span class="session-name">
                  {{ s.customerName || s.userName || '未命名' }}
                </span>
                <span
                  class="platform-badge"
                  :class="platformClass(s.platform)"
                >
                  {{ platformLabel(s.platform) }}
                </span>
              </div>
              <div class="session-preview">
                {{ s.lastMessage || s.lastMessagePreview || '暂无消息' }}
              </div>
            </div>
            <div v-if="unreadCount(s)" class="unread-badge">
              {{ unreadCount(s) > 99 ? '99+' : unreadCount(s) }}
            </div>
          </div>

          <el-empty
            v-if="!loading && filteredSessions.length === 0"
            description="暂无活跃会话"
            :image-size="48"
          />
        </div>
      </div>

      <!-- =================================================================== -->
      <!--  Right Panel — Chat Area                                            -->
      <!-- =================================================================== -->
      <div class="right-panel">
        <!-- Empty state when no session is selected -->
        <div v-if="!selectedSession" class="empty-state">
          <el-icon :size="72" color="#dcdfe6"><ChatDotRound /></el-icon>
          <p class="empty-text">选择一个会话开始查看</p>
        </div>

        <!-- Active chat -->
        <template v-else>
          <!-- Top: user info bar -->
          <div class="chat-header">
            <div class="chat-user-row">
              <span class="chat-user-name">
                {{ selectedSession.customerName || selectedSession.userName || '未命名' }}
              </span>
              <span
                class="platform-badge chat-platform"
                :class="platformClass(selectedSession.platform)"
              >
                {{ platformLabel(selectedSession.platform) }}
              </span>
              <el-tag
                v-for="tag in selectedSession.tags || []"
                :key="tag"
                size="small"
                type="info"
                effect="plain"
                class="user-tag"
              >
                {{ tag }}
              </el-tag>
            </div>
            <span class="chat-session-meta">
              会话ID: {{ selectedSession.id || selectedSession.sessionId }}
            </span>
          </div>

          <!-- Middle: message history -->
          <div ref="msgContainer" class="message-list">
            <div v-if="messagesLoading" class="msg-loading">
              <el-icon class="is-loading" :size="28"><Loading /></el-icon>
            </div>

            <template v-else>
              <div
                v-for="msg in messages"
                :key="msg.id || msg.messageId"
                class="msg-row"
                :class="isIncoming(msg) ? 'msg-in' : 'msg-out'"
              >
                <div
                  class="msg-bubble"
                  :class="isIncoming(msg) ? 'bubble-in' : 'bubble-out'"
                >
                  <div class="bubble-content">
                    {{ msg.content || msg.text || msg.message }}
                  </div>
                  <div class="bubble-time">
                    {{ formatTime(msg.timestamp || msg.time || msg.createdAt) }}
                  </div>
                </div>
              </div>

              <el-empty
                v-if="messages.length === 0"
                description="暂无消息"
                :image-size="48"
              />
            </template>
          </div>

          <!-- Bottom: input area -->
          <div class="chat-input">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="2"
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              resize="none"
              @keydown.enter.exact.prevent="handleSend"
            />
            <el-button
              type="primary"
              :loading="sending"
              :disabled="!inputMessage.trim()"
              @click="handleSend"
            >
              发送
            </el-button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, UserFilled, Loading } from '@element-plus/icons-vue'
import { getSessions, sendMessage } from '@/api'
import axios from 'axios'

// ===========================================================================
// Reactive state
// ===========================================================================
const sessions = ref([])
const selectedSessionId = ref(null)
const messages = ref([])
const inputMessage = ref('')
const platformFilter = ref('all')
const loading = ref(true)
const messagesLoading = ref(false)
const sending = ref(false)
const msgContainer = ref(null)

let refreshTimer = null

// ===========================================================================
// Computed
// ===========================================================================
const filteredSessions = computed(() => {
  if (platformFilter.value === 'all') return sessions.value
  return sessions.value.filter(
    (s) => (s.platform || '').toLowerCase() === platformFilter.value
  )
})

const selectedSession = computed(() => {
  if (!selectedSessionId.value) return null
  return (
    sessions.value.find(
      (s) => (s.id || s.sessionId) === selectedSessionId.value
    ) || null
  )
})

// ===========================================================================
// Helpers
// ===========================================================================
function platformLabel(platform) {
  const map = { taobao: '淘宝', douyin: '抖音', jd: '京东', pdd: '拼多多' }
  return map[(platform || '').toLowerCase()] || platform || '其他'
}

function platformClass(platform) {
  const p = (platform || '').toLowerCase()
  if (p === 'taobao') return 'plat-taobao'
  if (p === 'douyin') return 'plat-douyin'
  if (p === 'jd') return 'plat-jd'
  if (p === 'pdd') return 'plat-pdd'
  return 'plat-other'
}

function unreadCount(session) {
  return session.unreadCount ?? session.unread ?? 0
}

function isIncoming(msg) {
  const sender = (msg.sender || '').toLowerCase()
  if (sender === 'customer') return true
  if (sender === 'agent' || sender === 'ai' || sender === 'bot') return false
  const direction = (msg.direction || '').toLowerCase()
  if (direction === 'in') return true
  if (direction === 'out') return false
  // Default: treat as incoming
  return true
}

function formatTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (Number.isNaN(d.getTime())) return ts
    const now = new Date()
    const isToday =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    const time = d.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit'
    })
    if (isToday) return time
    return `${d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })} ${time}`
  } catch {
    return ts
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

// ===========================================================================
// Data fetching
// ===========================================================================
async function fetchSessions() {
  try {
    const data = await getSessions({ status: 'active' })
    sessions.value = Array.isArray(data) ? data : data?.list || data?.sessions || []

    // If the selected session no longer exists, clear it
    if (selectedSessionId.value) {
      const stillExists = sessions.value.some(
        (s) => (s.id || s.sessionId) === selectedSessionId.value
      )
      if (!stillExists) {
        selectedSessionId.value = null
        messages.value = []
      }
    }
  } catch (err) {
    console.error('Fetch sessions error:', err)
  } finally {
    loading.value = false
  }
}

async function fetchMessages(sessionId) {
  messagesLoading.value = true
  try {
    const res = await axios.get('/api/chat/messages', {
      params: { sessionId, session_id: sessionId }
    })
    // Unwrap possible response shapes
    const data = res.data
    if (data && typeof data === 'object' && 'data' in data && data.data !== undefined) {
      messages.value = Array.isArray(data.data) ? data.data : data.data.list || []
    } else if (Array.isArray(data)) {
      messages.value = data
    } else if (data && Array.isArray(data.list)) {
      messages.value = data.list
    } else if (data && Array.isArray(data.messages)) {
      messages.value = data.messages
    } else {
      messages.value = []
    }
  } catch (err) {
    console.error('Fetch messages error:', err)
    messages.value = []
  } finally {
    messagesLoading.value = false
    scrollToBottom()
  }
}

// ===========================================================================
// Event handlers
// ===========================================================================
function onSelectSession(session) {
  const id = session.id || session.sessionId
  if (id === selectedSessionId.value) return

  selectedSessionId.value = id
  messages.value = []
  inputMessage.value = ''

  // Reset unread for this session locally
  const found = sessions.value.find((s) => (s.id || s.sessionId) === id)
  if (found) {
    if (found.unreadCount !== undefined) found.unreadCount = 0
    if (found.unread !== undefined) found.unread = 0
  }

  fetchMessages(id)
}

async function handleSend() {
  const text = inputMessage.value.trim()
  if (!text || sending.value) return

  const sessionId = selectedSessionId.value
  if (!sessionId) {
    ElMessage.warning('请先选择一个会话')
    return
  }

  const payload = {
    sessionId,
    session_id: sessionId,
    message: text,
    content: text,
    type: 'text'
  }

  sending.value = true
  try {
    await sendMessage(payload)

    // Optimistically append the sent message
    messages.value.push({
      id: `local_${Date.now()}`,
      messageId: `local_${Date.now()}`,
      sender: 'agent',
      direction: 'out',
      content: text,
      message: text,
      timestamp: new Date().toISOString(),
      createdAt: new Date().toISOString()
    })

    inputMessage.value = ''
    scrollToBottom()
  } catch {
    // Error already shown by interceptor
  } finally {
    sending.value = false
  }
}

// ===========================================================================
// Watchers
// ===========================================================================
watch(
  () => messages.value.length,
  () => {
    scrollToBottom()
  }
)

// ===========================================================================
// Lifecycle
// ===========================================================================
onMounted(() => {
  fetchSessions()
  refreshTimer = setInterval(fetchSessions, 10_000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
/* ========================================================================== */
/*  Layout                                                                    */
/* ========================================================================== */
.live-chat {
  height: calc(100vh - 140px);
  min-height: 500px;
}

.split-container {
  display: flex;
  height: 100%;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

/* ---- Left Panel ---- */
.left-panel {
  width: 300px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  background: #fafbfc;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* ---- Session List ---- */
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: flex-start;
  padding: 12px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
}

.session-item:hover {
  background: #ecf5ff;
}

.session-item.active {
  background: #ecf5ff;
  box-shadow: inset 3px 0 0 #409eff;
}

.session-avatar {
  flex-shrink: 0;
  margin-right: 12px;
}

.session-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.session-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.session-name {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-preview {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

/* ---- Unread badge ---- */
.unread-badge {
  flex-shrink: 0;
  min-width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 10px;
  background: #f56c6c;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 0 6px;
  margin-left: 8px;
  margin-top: 2px;
}

/* ========================================================================== */
/*  Right Panel                                                               */
/* ========================================================================== */
.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* ---- Empty state ---- */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #c0c4cc;
}

.empty-text {
  font-size: 15px;
  color: #909399;
  margin: 0;
}

/* ---- Chat header ---- */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
  flex-shrink: 0;
}

.chat-user-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-user-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.chat-platform {
  font-size: 12px;
}

.user-tag {
  height: 22px;
  line-height: 20px;
  font-size: 11px;
}

.chat-session-meta {
  font-size: 12px;
  color: #a8abb2;
}

/* ========================================================================== */
/*  Message list — chat bubbles                                              */
/* ========================================================================== */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f5f7fa;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.msg-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: #909399;
}

/* ---- Message row ---- */
.msg-row {
  display: flex;
  max-width: 70%;
}

.msg-row.msg-in {
  align-self: flex-start;
  flex-direction: row;
}

.msg-row.msg-out {
  align-self: flex-end;
  flex-direction: row-reverse;
}

/* ---- Bubble ---- */
.msg-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  word-break: break-word;
  line-height: 1.55;
  position: relative;
}

/* Incoming — customer messages, left-aligned, grey */
.bubble-in {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-top-left-radius: 4px;
  color: #303133;
}

/* Outgoing — agent/AI messages, right-aligned, blue */
.bubble-out {
  background: #409eff;
  border-top-right-radius: 4px;
  color: #fff;
}

.bubble-content {
  font-size: 14px;
  white-space: pre-wrap;
}

.bubble-time {
  font-size: 11px;
  margin-top: 4px;
  opacity: 0.7;
  text-align: right;
}

/* ========================================================================== */
/*  Input area                                                                */
/* ========================================================================== */
.chat-input {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px 20px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  flex-shrink: 0;
}

.chat-input :deep(.el-textarea__inner) {
  font-size: 14px;
  line-height: 1.5;
  border-radius: 8px;
}

.chat-input .el-button {
  height: 40px;
  flex-shrink: 0;
}

/* ========================================================================== */
/*  Platform badges                                                           */
/* ========================================================================== */
.platform-badge {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.plat-taobao {
  background: #fff0e6;
  color: #e6732c;
  border: 1px solid #fddbc5;
}

.plat-douyin {
  background: #fef0f5;
  color: #e6457a;
  border: 1px solid #fcd4e3;
}

.plat-jd {
  background: #ffeaea;
  color: #c81623;
  border: 1px solid #fcc;
}

.plat-pdd {
  background: #fff5ee;
  color: #e8532e;
  border: 1px solid #fcdac8;
}

.plat-other {
  background: #f4f4f5;
  color: #909399;
  border: 1px solid #e9e9eb;
}

/* ========================================================================== */
/*  Scrollbar                                                                 */
/* ========================================================================== */
.session-list::-webkit-scrollbar,
.message-list::-webkit-scrollbar {
  width: 6px;
}

.session-list::-webkit-scrollbar-thumb,
.message-list::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}

.session-list::-webkit-scrollbar-thumb:hover,
.message-list::-webkit-scrollbar-thumb:hover {
  background: #c0c4cc;
}
</style>
