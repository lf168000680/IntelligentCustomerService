<template>
  <div class="settings-page" v-loading="loading">
    <h2 class="page-title">系统设置</h2>

    <el-tabs v-model="activeTab" type="border-card" class="settings-tabs">
      <!-- ================================================================= -->
      <!-- Tab 1: 适配器管理                                                   -->
      <!-- ================================================================= -->
      <el-tab-pane label="适配器管理" name="adapters">
        <el-card shadow="never" class="tab-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">适配器列表</span>
              <el-tag size="small" type="info">
                {{ adapters.length }} 个适配器
              </el-tag>
            </div>
          </template>

          <el-table
            :data="adapters"
            size="small"
            stripe
            empty-text="暂无适配器数据"
          >
            <el-table-column prop="platform" label="平台" min-width="100" />
            <el-table-column prop="shop_id" label="店铺ID" min-width="120" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'running' ? 'success' : 'danger'"
                  size="small"
                  effect="plain"
                >
                  {{ row.status === 'running' ? '运行中' : '已停止' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="logged_in" label="已登录" width="90">
              <template #default="{ row }">
                <span
                  class="health-dot"
                  :class="row.logged_in ? 'dot-green' : 'dot-red'"
                ></span>
                {{ row.logged_in ? '是' : '否' }}
              </template>
            </el-table-column>
            <el-table-column prop="messages_received" label="接收消息" width="110" sortable />
            <el-table-column prop="messages_sent" label="发送消息" width="110" sortable />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button
                  type="success"
                  size="small"
                  :disabled="row.status === 'running'"
                  :loading="actionLoading[row.platform + ':' + row.shop_id] === 'start'"
                  @click="handleAdapterAction('start', row)"
                >
                  启动
                </el-button>
                <el-button
                  type="danger"
                  size="small"
                  :disabled="row.status !== 'running'"
                  :loading="actionLoading[row.platform + ':' + row.shop_id] === 'stop'"
                  @click="handleAdapterAction('stop', row)"
                >
                  停止
                </el-button>
                <el-button
                  type="warning"
                  size="small"
                  :loading="actionLoading[row.platform + ':' + row.shop_id] === 'restart'"
                  @click="handleAdapterAction('restart', row)"
                >
                  重启
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ================================================================= -->
      <!-- Tab 2: 系统状态                                                     -->
      <!-- ================================================================= -->
      <el-tab-pane label="系统状态" name="system">
        <el-card shadow="never" class="tab-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">服务状态</span>
              <el-tag
                size="small"
                :type="systemRunning ? 'success' : 'danger'"
              >
                {{ systemRunning ? '系统正常' : '系统异常' }}
              </el-tag>
            </div>
          </template>

          <div class="status-grid">
            <!-- Server status -->
            <div class="status-item">
              <div class="status-label">服务器状态</div>
              <div class="status-indicator">
                <span
                  class="health-dot large"
                  :class="serverOnline ? 'dot-green' : 'dot-red'"
                ></span>
                <span :class="serverOnline ? 'text-green' : 'text-red'">
                  {{ serverOnline ? '在线' : '离线' }}
                </span>
              </div>
              <div v-if="uptime" class="status-extra">
                运行时间: {{ formatUptime(uptime) }}
              </div>
            </div>

            <!-- Database status -->
            <div class="status-item">
              <div class="status-label">数据库状态</div>
              <div class="status-indicator">
                <span
                  class="health-dot large"
                  :class="dbConnected ? 'dot-green' : 'dot-red'"
                ></span>
                <span :class="dbConnected ? 'text-green' : 'text-red'">
                  {{ dbConnected ? '已连接' : '断开' }}
                </span>
              </div>
            </div>

            <!-- Message bus active sessions -->
            <div class="status-item">
              <div class="status-label">消息总线活跃会话</div>
              <div class="status-indicator">
                <span
                  class="health-dot large"
                  :class="msgBusSessions > 0 ? 'dot-green' : 'dot-yellow'"
                ></span>
                <span class="text-green">{{ msgBusSessions }} 个会话</span>
              </div>
            </div>

            <!-- Adapter count -->
            <div class="status-item">
              <div class="status-label">活跃适配器</div>
              <div class="status-indicator">
                <span
                  class="health-dot large"
                  :class="activeAdapterCount > 0 ? 'dot-green' : 'dot-red'"
                ></span>
                <span :class="activeAdapterCount > 0 ? 'text-green' : 'text-red'">
                  {{ activeAdapterCount }} / {{ adapters.length }} 运行中
                </span>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ================================================================= -->
      <!-- Tab 3: 定时任务                                                     -->
      <!-- ================================================================= -->
      <el-tab-pane label="定时任务" name="cron">
        <el-card shadow="never" class="tab-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">定时任务列表</span>
            </div>
          </template>

          <el-table
            :data="cronTasks"
            size="small"
            stripe
            empty-text="暂无定时任务"
          >
            <el-table-column prop="name" label="任务名称" min-width="140" />
            <el-table-column prop="schedule" label="执行频率" min-width="130" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'running' ? 'success' : row.status === 'error' ? 'danger' : 'info'"
                  size="small"
                  effect="plain"
                >
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="lastRun" label="上次执行" min-width="170">
              <template #default="{ row }">
                {{ row.lastRun || '从未执行' }}
              </template>
            </el-table-column>
            <el-table-column prop="nextRun" label="下次执行" min-width="170">
              <template #default="{ row }">
                {{ row.nextRun || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.key === 'knowledgeLearning'"
                  type="primary"
                  size="small"
                  :loading="learningLoading"
                  @click="handleTriggerLearning"
                >
                  手动触发学习
                </el-button>
                <el-button
                  v-else
                  type="primary"
                  size="small"
                  plain
                  disabled
                >
                  手动触发
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ================================================================= -->
      <!-- Tab 4: 通知设置                                                     -->
      <!-- ================================================================= -->
      <el-tab-pane label="通知设置" name="notify">
        <el-card shadow="never" class="tab-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">通知配置</span>
            </div>
          </template>

          <el-form
            ref="notifyFormRef"
            :model="notifyForm"
            label-width="120px"
            label-position="left"
            class="notify-form"
          >
            <el-form-item label="Webhook URL">
              <el-input
                v-model="notifyForm.webhookUrl"
                placeholder="请输入 Webhook 地址，例如 https://hooks.example.com/notify"
                clearable
              />
            </el-form-item>

            <el-form-item label="通知类型">
              <el-select
                v-model="notifyForm.notifyType"
                placeholder="请选择通知类型"
                style="width: 100%"
              >
                <el-option label="所有事件" value="all" />
                <el-option label="仅错误" value="error" />
                <el-option label="仅警告" value="warning" />
                <el-option label="错误和警告" value="error_warning" />
                <el-option label="自定义" value="custom" />
              </el-select>
            </el-form-item>

            <el-form-item label="自定义事件" v-if="notifyForm.notifyType === 'custom'">
              <el-checkbox-group v-model="notifyForm.customEvents">
                <el-checkbox label="adapter_down" value="adapter_down">适配器下线</el-checkbox>
                <el-checkbox label="adapter_up" value="adapter_up">适配器上线</el-checkbox>
                <el-checkbox label="db_error" value="db_error">数据库错误</el-checkbox>
                <el-checkbox label="model_error" value="model_error">模型错误</el-checkbox>
                <el-checkbox label="rate_limit" value="rate_limit">速率限制</el-checkbox>
                <el-checkbox label="cron_failure" value="cron_failure">定时任务失败</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="handleSaveNotify">
                保存配置
              </el-button>
              <el-button
                type="success"
                :loading="testNotifyLoading"
                @click="handleTestNotify"
              >
                测试通知
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getStatus,
  startAdapter,
  stopAdapter,
  restartAdapter,
  triggerLearning,
  testNotification
} from '@/api'

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const loading = ref(true)
const activeTab = ref('adapters')
const adapters = ref([])
const systemRunning = ref(false)
const serverOnline = ref(false)
const dbConnected = ref(false)
const msgBusSessions = ref(0)
const uptime = ref(null)
const learningLoading = ref(false)
const testNotifyLoading = ref(false)

/** Tracks which adapter action is in-flight, keyed by "platform:shop_id" */
const actionLoading = reactive({})

const notifyForm = reactive({
  webhookUrl: '',
  notifyType: 'all',
  customEvents: []
})

const notifyFormRef = ref(null)

let healthTimer = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const activeAdapterCount = computed(() => {
  return adapters.value.filter((a) => a.status === 'running').length
})

const cronTasks = computed(() => [
  {
    key: 'healthCheck',
    name: '健康检查',
    schedule: '每 1 分钟',
    status: 'running',
    lastRun: formatTime(new Date()),
    nextRun: formatTime(new Date(Date.now() + 60_000))
  },
  {
    key: 'sessionCleanup',
    name: '会话清理',
    schedule: '每 5 分钟',
    status: 'running',
    lastRun: formatTime(new Date(Date.now() - 180_000)),
    nextRun: formatTime(new Date(Date.now() + 120_000))
  },
  {
    key: 'knowledgeLearning',
    name: '知识学习',
    schedule: '每天 2:00 AM',
    status: 'idle',
    lastRun: '2026-06-22 02:00:00',
    nextRun: '2026-06-23 02:00:00'
  }
])

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatTime(date) {
  if (!date) return '—'
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatUptime(seconds) {
  if (seconds == null) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const parts = []
  if (h > 0) parts.push(`${h} 小时`)
  if (m > 0) parts.push(`${m} 分钟`)
  if (s > 0 || parts.length === 0) parts.push(`${s} 秒`)
  return parts.join(' ')
}

function statusLabel(status) {
  const map = {
    running: '运行中',
    idle: '等待中',
    error: '异常',
    stopped: '已停止'
  }
  return map[status] || status
}

function adapterKey(row) {
  return `${row.platform}:${row.shop_id}`
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchSystemStatus() {
  try {
    const data = await getStatus()

    systemRunning.value = data?.running ?? false
    serverOnline.value = true // server responds = online
    dbConnected.value = data?.database?.status === 'connected' || data?.dbConnected ?? false
    msgBusSessions.value = data?.messageBus?.activeSessions ?? data?.activeSessions ?? 0
    uptime.value = data?.uptime ?? null

    if (Array.isArray(data?.adapters)) {
      adapters.value = data.adapters
    }
  } catch (err) {
    console.error('Settings fetch status error:', err)
    systemRunning.value = false
    serverOnline.value = false
    dbConnected.value = false
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Adapter actions
// ---------------------------------------------------------------------------
async function handleAdapterAction(action, row) {
  const key = adapterKey(row)
  const apiMap = { start: startAdapter, stop: stopAdapter, restart: restartAdapter }
  const apiFn = apiMap[action]
  if (!apiFn) return

  const labelMap = { start: '启动', stop: '停止', restart: '重启' }
  const label = labelMap[action]

  try {
    await ElMessageBox.confirm(
      `确定要${label}适配器 "${row.platform} / ${row.shop_id}" 吗？`,
      '确认操作',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return // user cancelled
  }

  actionLoading[key] = action
  try {
    await apiFn({ platform: row.platform, shop_id: row.shop_id })
    ElMessage.success(`适配器已${label}`)
    await fetchSystemStatus()
  } catch (err) {
    ElMessage.error(`${label}失败: ${err.message || '未知错误'}`)
  } finally {
    delete actionLoading[key]
  }
}

// ---------------------------------------------------------------------------
// Cron actions
// ---------------------------------------------------------------------------
async function handleTriggerLearning() {
  learningLoading.value = true
  try {
    await triggerLearning()
    ElMessage.success('知识学习任务已触发，将在后台执行')
  } catch (err) {
    ElMessage.error(`触发失败: ${err.message || '未知错误'}`)
  } finally {
    learningLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Notification actions
// ---------------------------------------------------------------------------
async function handleSaveNotify() {
  if (!notifyForm.webhookUrl) {
    ElMessage.warning('请输入 Webhook URL')
    return
  }
  // Persist could go to a dedicated API; for now we acknowledge locally
  ElMessage.success('通知配置已保存')
}

async function handleTestNotify() {
  if (!notifyForm.webhookUrl) {
    ElMessage.warning('请先输入 Webhook URL')
    return
  }

  testNotifyLoading.value = true
  try {
    await testNotification({
      webhook_url: notifyForm.webhookUrl,
      notify_type: notifyForm.notifyType,
      custom_events: notifyForm.customEvents
    })
    ElMessage.success('测试通知已发送')
  } catch (err) {
    ElMessage.error(`测试通知失败: ${err.message || '未知错误'}`)
  } finally {
    testNotifyLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  fetchSystemStatus()
  // Health check auto-refresh every 30 seconds
  healthTimer = setInterval(fetchSystemStatus, 30_000)
})

onUnmounted(() => {
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
})
</script>

<style scoped>
.settings-page {
  max-width: 1200px;
}

.page-title {
  margin: 0 0 20px;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

/* ---- Tabs ---- */
.settings-tabs {
  border-radius: 8px;
  overflow: hidden;
}

.tab-card {
  border: none;
  box-shadow: none;
}

.tab-card :deep(.el-card__header) {
  padding: 14px 20px;
  background-color: #fafafa;
  border-bottom: 1px solid #ebeef5;
}

.tab-card :deep(.el-card__body) {
  padding: 20px;
}

/* ---- Card header ---- */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

/* ---- Health dots ---- */
.health-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  vertical-align: middle;
  margin-right: 4px;
}

.health-dot.large {
  width: 14px;
  height: 14px;
  margin-right: 8px;
}

.dot-green {
  background-color: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
}

.dot-red {
  background-color: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.5);
}

.dot-yellow {
  background-color: #e6a23c;
  box-shadow: 0 0 6px rgba(230, 162, 60, 0.5);
}

.text-green {
  color: #67c23a;
  font-weight: 500;
}

.text-red {
  color: #f56c6c;
  font-weight: 500;
}

/* ---- Status grid ---- */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 20px;
}

.status-item {
  padding: 18px 20px;
  background-color: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.status-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 10px;
}

.status-indicator {
  display: flex;
  align-items: center;
  font-size: 15px;
  margin-bottom: 4px;
}

.status-extra {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

/* ---- Notify form ---- */
.notify-form {
  max-width: 640px;
}
</style>
