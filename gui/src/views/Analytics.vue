<template>
  <div class="analytics-page" v-loading="loading">
    <!-- Header with date range picker -->
    <div class="page-header">
      <h2 class="page-title">数据分析</h2>
      <div class="page-actions">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :shortcuts="dateShortcuts"
          value-format="YYYY-MM-DD"
          @change="onDateChange"
        />
      </div>
    </div>

    <!-- Stats overview cards -->
    <el-row :gutter="20" class="stat-row">
      <el-col v-for="card in statCards" :key="card.key" :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-card-content">
            <div class="stat-info">
              <div class="stat-label">{{ card.label }}</div>
              <div class="stat-value">{{ card.value }}</div>
              <div v-if="card.sub" class="stat-sub">{{ card.sub }}</div>
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
      <!-- Left: 热门问题排行 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">热门问题排行</span>
              <el-tag size="small" type="info">{{ topIssues.length }} 项</el-tag>
            </div>
          </template>
          <div v-if="topIssues.length > 0" class="issue-list">
            <div
              v-for="(item, idx) in topIssues"
              :key="item.intent || item.name || idx"
              class="issue-row"
            >
              <div class="issue-rank">
                <span class="rank-badge" :class="'rank-' + (idx + 1)">{{ idx + 1 }}</span>
              </div>
              <div class="issue-name">{{ item.intent || item.name || item.label }}</div>
              <div class="issue-bar-wrap">
                <div
                  class="issue-bar"
                  :style="{ width: barPercent(item.count) }"
                ></div>
              </div>
              <div class="issue-count">{{ item.count ?? 0 }}</div>
            </div>
          </div>
          <el-empty v-else description="暂无热门问题数据" :image-size="64" />
        </el-card>
      </el-col>

      <!-- Right: 模型使用统计 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">模型使用统计</span>
              <el-tag size="small" :type="modelUsage.length > 0 ? 'info' : 'warning'">
                {{ modelUsage.length }} 个模型
              </el-tag>
            </div>
          </template>
          <el-table
            :data="modelUsage"
            size="small"
            max-height="360"
            stripe
            empty-text="暂无模型使用数据"
          >
            <el-table-column prop="model" label="模型名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="calls" label="调用次数" width="100" align="center" />
            <el-table-column label="平均延迟" width="110" align="center">
              <template #default="{ row }">
                {{ formatLatency(row.avgLatency ?? row.avg_latency) }}
              </template>
            </el-table-column>
            <el-table-column label="健康" width="80" align="center">
              <template #default="{ row }">
                <span
                  class="health-dot"
                  :class="row.healthy ? 'dot-green' : 'dot-red'"
                ></span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 每日趋势 -->
    <el-card shadow="hover" class="section-card trend-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">每日趋势</span>
        </div>
      </template>
      <div v-if="dailyStats.length > 0" class="trend-list">
        <div
          v-for="(day, idx) in dailyStats"
          :key="day.date || idx"
          class="trend-row"
        >
          <div class="trend-date">{{ day.date || day.label }}</div>
          <div class="trend-values">
            <span class="trend-item">
              对话 <strong>{{ day.conversations ?? day.count ?? 0 }}</strong>
            </span>
            <span class="trend-item">
              解决率 <strong>{{ formatPercent(day.resolveRate ?? day.resolve_rate) }}</strong>
            </span>
            <span class="trend-item">
              满意度 <strong>{{ formatPercent(day.satisfaction) }}</strong>
            </span>
          </div>
        </div>
      </div>
      <div v-else class="trend-placeholder">
        <el-icon :size="48" color="#c0c4cc"><TrendCharts /></el-icon>
        <p class="trend-placeholder-text">选择更长的日期范围以查看每日趋势数据</p>
        <p class="trend-placeholder-hint">数据将从 /api/analytics/daily 接口加载</p>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import {
  ChatDotRound, Check, Timer, Star, TrendCharts
} from '@element-plus/icons-vue'
import { getOverview, getTopIssues, getModelUsage, getDailyStats } from '@/api'

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------
function todayStr() {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

function daysAgoStr(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const loading = ref(true)
const overview = ref({})
const topIssues = ref([])
const modelUsage = ref([])
const dailyStats = ref([])

const dateRange = ref([daysAgoStr(7), todayStr()])

const dateShortcuts = [
  { text: '最近一周', value: () => [daysAgoStr(7), todayStr()] },
  { text: '最近两周', value: () => [daysAgoStr(14), todayStr()] },
  { text: '最近一个月', value: () => [daysAgoStr(30), todayStr()] },
  { text: '最近三个月', value: () => [daysAgoStr(90), todayStr()] }
]

// ---------------------------------------------------------------------------
// Computed: stat cards
// ---------------------------------------------------------------------------
const statCards = computed(() => [
  {
    key: 'totalConversations',
    label: '总对话数',
    value: overview.value.totalConversations ?? overview.value.total_conversations ?? overview.value.total ?? 0,
    sub: '',
    icon: ChatDotRound
  },
  {
    key: 'aiResolveRate',
    label: 'AI 解决率',
    value: formatPercent(overview.value.aiResolveRate ?? overview.value.ai_resolve_rate ?? overview.value.resolveRate ?? overview.value.resolve_rate),
    sub: '',
    icon: Check
  },
  {
    key: 'avgResponseTime',
    label: '平均响应时间',
    value: formatLatency(overview.value.avgResponseTime ?? overview.value.avg_response_time),
    sub: '',
    icon: Timer
  },
  {
    key: 'satisfaction',
    label: '客户满意度',
    value: formatPercent(overview.value.satisfaction),
    sub: overview.value.satisfactionCount != null ? `${overview.value.satisfactionCount || overview.value.satisfaction_count || 0} 条评价` : '',
    icon: Star
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

function formatLatency(val) {
  if (val == null) return '—'
  const num = Number(val)
  if (Number.isNaN(num)) return '—'
  if (num >= 1000) return `${(num / 1000).toFixed(1)}s`
  return `${Math.round(num)}ms`
}

function barPercent(count) {
  if (!topIssues.value.length) return '0%'
  const max = Math.max(...topIssues.value.map((i) => i.count ?? 0))
  if (max <= 0) return '0%'
  return ((count / max) * 100).toFixed(1) + '%'
}

// ---------------------------------------------------------------------------
// Date range params helper
// ---------------------------------------------------------------------------
function dateParams() {
  const [start, end] = dateRange.value || []
  return { start, end }
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchData() {
  loading.value = true
  try {
    const params = dateParams()
    const [ov, issues, usage, daily] = await Promise.all([
      getOverview(params).catch(() => null),
      getTopIssues(params).catch(() => []),
      getModelUsage(params).catch(() => []),
      getDailyStats(params).catch(() => [])
    ])

    if (ov && typeof ov === 'object') overview.value = ov
    if (Array.isArray(issues)) topIssues.value = issues
    if (Array.isArray(usage)) modelUsage.value = usage
    if (Array.isArray(daily)) dailyStats.value = daily
  } catch (err) {
    console.error('Analytics fetch error:', err)
  } finally {
    loading.value = false
  }
}

function onDateChange() {
  fetchData()
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.analytics-page {
  max-width: 1400px;
}

/* ---- Page Header ---- */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.page-actions {
  display: flex;
  gap: 10px;
  align-items: center;
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

.stat-sub {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
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

/* ---- Hot Issues (bar chart) ---- */
.issue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.issue-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.issue-rank {
  width: 28px;
  flex-shrink: 0;
  text-align: center;
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  background-color: #ebeef5;
  color: #909399;
}

.rank-badge.rank-1 {
  background-color: #f56c6c;
  color: #fff;
}

.rank-badge.rank-2 {
  background-color: #e6a23c;
  color: #fff;
}

.rank-badge.rank-3 {
  background-color: #409eff;
  color: #fff;
}

.issue-name {
  width: 120px;
  flex-shrink: 0;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.issue-bar-wrap {
  flex: 1;
  min-width: 0;
  height: 16px;
  background-color: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}

.issue-bar {
  height: 100%;
  background: linear-gradient(90deg, #409eff, #66b1ff);
  border-radius: 4px;
  transition: width 0.4s ease;
  min-width: 4px;
}

.issue-count {
  width: 36px;
  flex-shrink: 0;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
}

/* ---- Model Usage Table ---- */

/* ---- Health dot ---- */
.health-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-green {
  background-color: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
}

.dot-red {
  background-color: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.5);
}

/* ---- Daily Trend ---- */
.trend-card {
  margin-bottom: 20px;
}

.trend-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.trend-row {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  background-color: #fafafa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.trend-date {
  width: 100px;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.trend-values {
  display: flex;
  gap: 24px;
  flex: 1;
}

.trend-item {
  font-size: 13px;
  color: #606266;
}

.trend-item strong {
  color: #303133;
  margin-left: 4px;
}

/* ---- Trend Placeholder ---- */
.trend-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0 20px;
  color: #c0c4cc;
}

.trend-placeholder-text {
  margin: 12px 0 4px;
  font-size: 14px;
  color: #909399;
}

.trend-placeholder-hint {
  margin: 0;
  font-size: 12px;
  color: #c0c4cc;
}
</style>
