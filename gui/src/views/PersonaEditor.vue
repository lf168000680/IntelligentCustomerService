<template>
  <div class="persona-editor">
    <!-- ================================================================
         Top Toolbar
         ================================================================ -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-label">Persona:</span>
        <el-select
          v-model="selectedPersona"
          placeholder="选择 Persona"
          size="default"
          class="persona-select"
        >
          <el-option
            v-for="p in personas"
            :key="p.id || p.name"
            :label="p.name || String(p.id)"
            :value="p.name || String(p.id)"
          />
        </el-select>
      </div>

      <div class="toolbar-right">
        <el-button type="primary" :loading="saving" @click="handleSave">
          <el-icon v-if="!saving"><Check /></el-icon>
          <span>保存</span>
        </el-button>
        <el-button type="success" :loading="compiling" @click="handleCompile">
          <el-icon v-if="!compiling"><View /></el-icon>
          <span>编译预览</span>
        </el-button>
        <el-button type="warning" @click="focusTestChat">
          <el-icon><ChatDotRound /></el-icon>
          <span>测试</span>
        </el-button>
      </div>
    </div>

    <!-- ================================================================
         Tab Bar
         ================================================================ -->
    <div class="editor-tabs">
      <button
        v-for="tab in tabs"
        :key="tab"
        :class="['tab-btn', { active: currentTab === tab }]"
        @click="currentTab = tab"
      >
        {{ tab }}
      </button>
      <div class="tab-spacer"></div>
      <span v-if="loading" class="tab-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </span>
    </div>

    <!-- ================================================================
         Split Body: Editor (60%) | Preview + Chat (40%)
         ================================================================ -->
    <div class="editor-body">
      <!--  Left: Markdown Editor  -->
      <div class="editor-left">
        <textarea
          v-model="editingContent"
          class="editor-textarea"
          :placeholder="`编辑 ${currentTab} 内容...`"
          spellcheck="false"
        ></textarea>
      </div>

      <!--  Right: Preview Panel + Test Chat  -->
      <div class="editor-right">
        <!--  Compiled Prompt Preview  -->
        <div class="preview-panel">
          <div class="panel-header">
            <el-icon><Document /></el-icon>
            <span>编译预览</span>
            <span v-if="compiledPrompt" class="panel-badge">已编译</span>
          </div>
          <div class="panel-body">
            <pre v-if="compiledPrompt" class="compiled-content">{{ compiledPrompt }}</pre>
            <div v-else class="panel-placeholder">
              <el-icon :size="32"><MagicStick /></el-icon>
              <p>点击「编译预览」查看编译后的系统提示词</p>
            </div>
          </div>
        </div>

        <!--  Test Chat  -->
        <div class="chat-panel" ref="chatPanelRef">
          <div class="panel-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>测试对话</span>
            <span v-if="testing" class="panel-badge testing">回复中...</span>
          </div>
          <div class="chat-messages" ref="chatMessagesRef">
            <div v-if="testMessages.length === 0" class="panel-placeholder">
              <el-icon :size="32"><ChatLineSquare /></el-icon>
              <p>发送消息测试当前 Persona 的回复效果</p>
            </div>
            <div
              v-for="(msg, idx) in testMessages"
              :key="idx"
              :class="['chat-bubble', msg.role]"
            >
              <div class="bubble-label">
                {{ msg.role === 'user' ? '你' : msg.role === 'assistant' ? 'AI' : '错误' }}
              </div>
              <div class="bubble-content">{{ msg.content }}</div>
            </div>
          </div>
          <div class="chat-input-area">
            <el-input
              v-model="testInput"
              placeholder="输入测试消息，Enter 发送..."
              :disabled="testing || !selectedPersona"
              class="chat-input"
              @keyup.enter="handleTestSend"
            />
            <el-button
              type="primary"
              :loading="testing"
              :disabled="!testInput.trim() || !selectedPersona"
              size="small"
              class="send-btn"
              @click="handleTestSend"
            >
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * PersonaEditor.vue — 核心 Persona 文档编辑器
 *
 * Features:
 *  - Persona 选择器，加载 API 列表
 *  - SOUL.md / STYLE.md / SKILL.md / MEMORY.md / RULES.md 多标签编辑
 *  - 左侧 Markdown 编辑器 (暗色主题)
 *  - 右上编译预览面板
 *  - 右下测试对话面板
 */
import { ref, watch, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listPersonas,
  getPersonaFile,
  savePersonaFile,
  compilePersona,
  testPersonaChat
} from '@/api'

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const personas = ref([])
const selectedPersona = ref('')
const currentTab = ref('SOUL.md')
const editingContent = ref('')
const compiledPrompt = ref('')
const testMessages = ref([])
const testInput = ref('')

const loading = ref(false)
const saving = ref(false)
const compiling = ref(false)
const testing = ref(false)

const tabs = ['SOUL.md', 'STYLE.md', 'SKILL.md', 'MEMORY.md', 'RULES.md']

// Template refs
const chatMessagesRef = ref(null)
const chatPanelRef = ref(null)

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  await loadPersonas()
})

// ---------------------------------------------------------------------------
// Watchers
// ---------------------------------------------------------------------------

/** Reload file content whenever the active tab changes */
watch(currentTab, () => {
  if (selectedPersona.value) {
    loadFileContent()
  }
})

/** Reset previews & reload when a different persona is selected */
watch(selectedPersona, () => {
  compiledPrompt.value = ''
  testMessages.value = []
  if (selectedPersona.value) {
    loadFileContent()
  }
})

// ---------------------------------------------------------------------------
// Data loading helpers
// ---------------------------------------------------------------------------

async function loadPersonas() {
  try {
    const data = await listPersonas()
    personas.value = data?.personas || (Array.isArray(data) ? data : [])
    if (personas.value.length > 0) {
      const first = personas.value[0]
      selectedPersona.value = first.name || String(first.id)
    }
  } catch {
    // API interceptor already shows error messages
  }
}

async function loadFileContent() {
  if (!selectedPersona.value) return
  loading.value = true
  try {
    const data = await getPersonaFile(selectedPersona.value, currentTab.value)
    editingContent.value = typeof data === 'string'
      ? data
      : (data?.content ?? '')
  } catch {
    editingContent.value = ''
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Toolbar actions
// ---------------------------------------------------------------------------

async function handleSave() {
  if (!selectedPersona.value) {
    ElMessage.warning('请先选择 Persona')
    return
  }
  saving.value = true
  try {
    await savePersonaFile(selectedPersona.value, currentTab.value, editingContent.value)
    ElMessage.success('保存成功')
  } catch {
    // error already toasted by interceptor
  } finally {
    saving.value = false
  }
}

async function handleCompile() {
  if (!selectedPersona.value) {
    ElMessage.warning('请先选择 Persona')
    return
  }
  compiling.value = true
  try {
    const data = await compilePersona(selectedPersona.value)
    compiledPrompt.value = typeof data === 'string'
      ? data
      : JSON.stringify(data, null, 2)
    ElMessage.success('编译成功')
  } catch {
    // error already toasted by interceptor
  } finally {
    compiling.value = false
  }
}

function focusTestChat() {
  const el = chatPanelRef.value
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// ---------------------------------------------------------------------------
// Test chat
// ---------------------------------------------------------------------------

async function handleTestSend() {
  const message = testInput.value.trim()
  if (!message || !selectedPersona.value || testing.value) return

  testInput.value = ''
  testMessages.value.push({ role: 'user', content: message })
  scrollChatToBottom()

  testing.value = true
  try {
    const data = await testPersonaChat(selectedPersona.value, message)
    const reply = typeof data === 'string'
      ? data
      : (data?.reply || data?.message || data?.content || JSON.stringify(data))
    testMessages.value.push({ role: 'assistant', content: reply })
  } catch {
    testMessages.value.push({ role: 'error', content: '请求失败，请重试' })
  } finally {
    testing.value = false
    scrollChatToBottom()
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatMessagesRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}
</script>

<style scoped>
/* ==========================================================================
   PersonaEditor — Root
   ========================================================================== */
.persona-editor {
  height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

/* ==========================================================================
   Toolbar
   ========================================================================== */
.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  white-space: nowrap;
}

.persona-select {
  width: 210px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ==========================================================================
   Tab Bar
   ========================================================================== */
.editor-tabs {
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
  flex-shrink: 0;
}

.tab-btn {
  padding: 10px 20px;
  border: none;
  background: transparent;
  color: #909399;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', 'Menlo', monospace;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
  outline: none;
  user-select: none;
}

.tab-btn:hover {
  color: #409eff;
}

.tab-btn.active {
  color: #409eff;
  border-bottom-color: #409eff;
}

.tab-spacer {
  flex: 1;
}

.tab-loading {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #909399;
}

/* ==========================================================================
   Editor Body — Split Layout
   ========================================================================== */
.editor-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 500px;
}

/* ---- Left Panel: Editor ---- */
.editor-left {
  width: 60%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #ebeef5;
}

.editor-textarea {
  flex: 1;
  width: 100%;
  padding: 20px;
  border: none;
  outline: none;
  resize: none;
  background-color: #1e1e1e;
  color: #d4d4d4;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', 'Menlo', 'Courier New', monospace;
  font-size: 14px;
  line-height: 1.7;
  tab-size: 2;
}

.editor-textarea::placeholder {
  color: #6a6a6a;
  font-style: italic;
}

/* Dark scrollbar for editor */
.editor-textarea::-webkit-scrollbar {
  width: 8px;
}

.editor-textarea::-webkit-scrollbar-track {
  background: #252526;
}

.editor-textarea::-webkit-scrollbar-thumb {
  background-color: #424242;
  border-radius: 4px;
}

.editor-textarea::-webkit-scrollbar-thumb:hover {
  background-color: #555;
}

/* ---- Right Panel: Preview + Chat ---- */
.editor-right {
  width: 40%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}

/* ==========================================================================
   Panel chrome (Preview & Chat share these)
   ========================================================================== */
.preview-panel,
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview-panel {
  border-bottom: 1px solid #ebeef5;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  flex-shrink: 0;
  user-select: none;
}

.panel-header .el-icon {
  color: #909399;
}

.panel-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  padding: 2px 8px;
  border-radius: 10px;
  background: #e1f3d8;
  color: #67c23a;
}

.panel-badge.testing {
  background: #faecd8;
  color: #e6a23c;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.5; }
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.panel-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
  gap: 10px;
  text-align: center;
  padding: 20px;
}

.panel-placeholder p {
  font-size: 13px;
  margin: 0;
  line-height: 1.5;
}

.compiled-content {
  margin: 0;
  padding: 0;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', 'Menlo', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  background: transparent;
}

/* ==========================================================================
   Chat Panel — messages
   ========================================================================== */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.chat-bubble.user {
  align-self: flex-end;
  background: #409eff;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.chat-bubble.assistant {
  align-self: flex-start;
  background: #f0f2f5;
  color: #303133;
  border-bottom-left-radius: 4px;
}

.chat-bubble.error {
  align-self: center;
  background: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fde2e2;
  font-size: 12px;
  max-width: 90%;
}

.bubble-label {
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 4px;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.bubble-content {
  white-space: pre-wrap;
}

/* ---- Chat input area ---- */
.chat-input-area {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #ebeef5;
  flex-shrink: 0;
}

.chat-input {
  flex: 1;
}

.send-btn {
  flex-shrink: 0;
}

/* ==========================================================================
   Responsive
   ========================================================================== */
@media (max-width: 1024px) {
  .editor-body {
    flex-direction: column;
  }

  .editor-left {
    width: 100%;
    min-height: 300px;
    border-right: none;
    border-bottom: 1px solid #ebeef5;
  }

  .editor-right {
    width: 100%;
    min-height: 450px;
  }
}

@media (max-width: 768px) {
  .editor-toolbar {
    flex-wrap: wrap;
    gap: 8px;
  }

  .toolbar-right {
    flex-wrap: wrap;
  }

  .persona-select {
    width: 150px;
  }

  .tab-btn {
    padding: 8px 12px;
    font-size: 12px;
  }
}
</style>
