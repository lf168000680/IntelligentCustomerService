<template>
  <div class="dashboard" v-loading="loading">
    <!-- Stat Cards -->
    <el-row :gutter="20" class="stat-row">
      <el-col v-for="card in statCards" :key="card.key" :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-card-content">
            <div class="stat-info">
              <div class="stat-label">{{ card.label }}</div>
              <div class="stat-value">{{ card.value }}</div>
            </div>
            <div class="stat-icon">
              <el-icon :size="36">
                <component :is="card.icon" />
              </el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Two-column detail grid -->
    <el-row :gutter="20" class="detail-row">
      <!-- Left: Active sessions table -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">实时会话列表</span>
              <el-tag size="small" type="info">{{ sessions.length }} 个活跃</el-tag>
            </div>
          </template>
          <el-table
            :data="sessions"
            size="small"
            max-height="360"
            stripe
            empty-text="暂无活跃会话"
          >
            <el-table-column prop="sessionId" label="会话ID" min-width="140" show-overflow-tooltip />
            <el-table-column prop="customerName" label="客户" min-width="100" />
            <el-table-column prop="personaName" label="AI 角色" min-width="120" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'active' ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                >
                  {{ row.status === 'active' ? '进行中' : '等待中' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- Right: Model health status -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">模型健康状态</span>
              <el-tag
                size="small"
                :type="activeModelCount > 0 ? 'success' : 'danger'"
              >
                {{ activeModelCount }} / {{ models.length }} 健康
              </el-tag>
            </div>
          </template>
          <div v-if="models.length > 0" class="model-list">
            <div
              v-for="model in models"
              :key="model.id || model.name"
              class="model-item"
            >
              <div class="model-name">
                <span
                  class="health-dot"
                  :class="model.healthy ? 'dot-green' : 'dot-red'"
                ></span>
                {{ model.name || model.id }}
              </div>
              <el-tag
                size="small"
                :type="model.healthy ? 'success' : 'danger'"
                effect="plain"
              >
                {{ model.healthy ? '正常' : '离线' }}
              </el-tag>
            </div>
          </div>
          <el-empty v-else description="暂无模型数据" :image-size="64" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChatDotRound, Check, Cpu, Collection } from '@element-plus/icons-vue'
import { ElCard, ElRow, ElCol, ElStatistic, ElTable, ElTableColumn, ElTag, ElIcon, ElEmpty } from 'element-plus'
import { getSessions, getModelsStatus, getOverview, listKnowledge } from '@/api'

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const loading = ref(true)
const sessions = ref([])
const models = ref([])
const overview = ref({})
const knowledgeTotal = ref(0)

let refreshTimer = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const activeModelCount = computed(() => {
  return models.value.filter((m) => m.healthy).length
})

const statCards = computed(() => [
  {
    key: 'todaySessions',
    label: '今日会话',
    value: overview.value.todaySessions ?? overview.value.totalConversations ?? 0,
    icon: ChatDotRound
  },
  {
    key: 'aiReplyRate',
    label: 'AI回复率',
    value: formatPercent(overview.value.aiReplyRate ?? overview.value.replyRate ?? 0),
    icon: Check
  },
  {
    key: 'activeModels',
    label: '活跃模型数',
    value: activeModelCount.value,
    icon: Cpu
  },
  {
    key: 'knowledgeCount',
    label: '知识库条目数',
    value: knowledgeTotal.value,
    icon: Collection
  }
])

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatPercent(val) {
  if (val == null) return '0%'
  const num = Number(val)
  if (Number.isNaN(num)) return '0%'
  return `${num.toFixed(1)}%`
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchDashboardData() {
  try {
    const results = await Promise.all([
      getOverview().catch(() => null),
      getSessions({ status: 'active' }).catch(() => []),
      getModelsStatus().catch(() => []),
      listKnowledge({ page: 1, pageSize: 1 }).catch(() => null)
    ])

    const [ov, sess, mod, kb] = results

    if (ov && typeof ov === 'object') overview.value = ov
    if (Array.isArray(sess)) sessions.value = sess
    if (Array.isArray(mod)) models.value = mod

    // Unwrap knowledge total from paginated response
    if (kb) {
      if (typeof kb.total === 'number') {
        knowledgeTotal.value = kb.total
      } else if (Array.isArray(kb)) {
        knowledgeTotal.value = kb.length
      }
    }
  } catch (err) {
    console.error('Dashboard fetch error:', err)
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  fetchDashboardData()
  refreshTimer = setInterval(fetchDashboardData, 10_000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.dashboard {
  max-width: 1400px;
}

/* ---- Stat Cards ---- */
.stat-row {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 8px;
}

.stat-card :deep(.el-card__body) {
  padding: 20px 24px;
}

.stat-card-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stat-info {
  flex: 1;
  min-width: 0;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-icon {
  flex-shrink: 0;
  margin-left: 16px;
  color: #409eff;
  opacity: 0.7;
}

/* ---- Detail Row ---- */
.detail-row {
  margin-bottom: 20px;
}

.section-card {
  border-radius: 8px;
  height: 100%;
}

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

/* ---- Model Health List ---- */
.model-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.model-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background-color: #fafafa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.model-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #303133;
}

.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-green {
  background-color: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
}

.dot-red {
  background-color: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.5);
}
</style>
