<template>
  <div class="tools-config-page">
    <!-- ==================================================================== -->
    <!--  Page Header                                                         -->
    <!-- ==================================================================== -->
    <div class="page-header">
      <h2 class="page-title">Agent 工具管理</h2>
      <div class="page-actions">
        <el-button @click="refreshTools" :loading="refreshing" :icon="Refresh">
          刷新状态
        </el-button>
      </div>
    </div>

    <!-- ==================================================================== -->
    <!--  Stats Row                                                           -->
    <!-- ==================================================================== -->
    <el-row :gutter="20" class="stat-row">
      <el-col v-for="card in statCards" :key="card.key" :xs="24" :sm="8" :lg="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-card-content">
            <div class="stat-info">
              <div class="stat-label">{{ card.label }}</div>
              <div class="stat-value">{{ card.value }}</div>
            </div>
            <div class="stat-icon">
              <el-icon :size="32">
                <component :is="card.icon" />
              </el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================================================================== -->
    <!--  Tools Table                                                         -->
    <!-- ==================================================================== -->
    <el-table
      :data="tools"
      stripe
      border
      v-loading="loading"
      row-key="name"
      empty-text="暂无工具配置"
      class="tools-table"
    >
      <!-- Tool Name -->
      <el-table-column label="工具名称" min-width="180">
        <template #default="{ row }">
          <div class="tool-name-cell">
            <el-icon :size="18" class="tool-icon" :style="{ color: iconColor(row) }">
              <component :is="toolIcon(row.name)" />
            </el-icon>
            <span class="tool-name-text">{{ row.displayName || row.name }}</span>
          </div>
        </template>
      </el-table-column>

      <!-- Description -->
      <el-table-column label="描述" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="cell-text">{{ row.description || '暂无描述' }}</span>
        </template>
      </el-table-column>

      <!-- Category -->
      <el-table-column label="分类" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="categoryTagType(row.category)" effect="light" size="small">
            {{ row.category || '未分类' }}
          </el-tag>
        </template>
      </el-table-column>

      <!-- Parameter Schema (collapsible indicator) -->
      <el-table-column label="参数" width="100" align="center">
        <template #default="{ row }">
          <el-popover
            placement="bottom"
            :width="360"
            trigger="click"
            :show-after="200"
          >
            <template #reference>
              <el-button link type="primary" size="small">
                {{ (row.parameters || []).length }} 个参数
              </el-button>
            </template>
            <div class="params-schema">
              <div class="params-title">参数定义</div>
              <div
                v-for="(param, idx) in (row.parameters || [])"
                :key="idx"
                class="param-item"
              >
                <div class="param-header">
                  <span class="param-name">{{ param.name }}</span>
                  <el-tag
                    size="small"
                    :type="param.required ? 'danger' : 'info'"
                    effect="plain"
                  >
                    {{ param.required ? '必填' : '可选' }}
                  </el-tag>
                </div>
                <div class="param-type">{{ param.type || 'string' }}</div>
                <div v-if="param.description" class="param-desc">{{ param.description }}</div>
                <div v-if="param.default !== undefined" class="param-default">
                  默认值: <code>{{ param.default }}</code>
                </div>
              </div>
              <div v-if="!row.parameters || row.parameters.length === 0" class="params-empty">
                无参数
              </div>
            </div>
          </el-popover>
        </template>
      </el-table-column>

      <!-- Enabled -->
      <el-table-column label="启用" width="90" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(val) => toggleEnabled(row, val)"
            size="small"
          />
        </template>
      </el-table-column>

      <!-- Test Button -->
      <el-table-column label="操作" width="100" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            type="warning"
            size="small"
            :icon="CaretRight"
            :disabled="!row.enabled"
            @click="openTestDialog(row)"
          >
            测试
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- ==================================================================== -->
    <!--  Test Dialog                                                         -->
    <!-- ==================================================================== -->
    <el-dialog
      v-model="testDialogVisible"
      :title="`测试工具 — ${testTarget?.displayName || testTarget?.name || ''}`"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <!-- Tool info -->
      <el-descriptions v-if="testTarget" :column="2" border size="small" class="test-descriptions">
        <el-descriptions-item label="工具名称">
          {{ testTarget.displayName || testTarget.name }}
        </el-descriptions-item>
        <el-descriptions-item label="分类">
          <el-tag :type="categoryTagType(testTarget.category)" size="small" effect="plain">
            {{ testTarget.category || '未分类' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">
          {{ testTarget.description || '暂无描述' }}
        </el-descriptions-item>
      </el-descriptions>

      <!-- Parameter inputs -->
      <div v-if="testTarget && testTarget.parameters && testTarget.parameters.length > 0" class="test-params-section">
        <h4 class="section-subtitle">输入参数</h4>
        <el-form
          ref="testFormRef"
          :model="testForm"
          label-width="110px"
          label-position="right"
          class="test-form"
        >
          <el-form-item
            v-for="(param, idx) in testTarget.parameters"
            :key="param.name"
            :label="param.name"
            :prop="param.name"
            :rules="param.required ? [{ required: true, message: `请输入 ${param.name}`, trigger: 'blur' }] : []"
          >
            <el-input
              v-if="param.type === 'string' || param.type === 'text' || !param.type"
              v-model="testForm[param.name]"
              :placeholder="param.description || `输入 ${param.name}`"
            />
            <el-input-number
              v-else-if="param.type === 'number' || param.type === 'integer'"
              v-model="testForm[param.name]"
              :placeholder="param.description || `输入 ${param.name}`"
              style="width: 100%"
            />
            <el-switch
              v-else-if="param.type === 'boolean'"
              v-model="testForm[param.name]"
            />
            <el-input
              v-else
              v-model="testForm[param.name]"
              type="textarea"
              :rows="3"
              :placeholder="`JSON 格式输入 (${param.type})`"
            />
            <div v-if="param.description" class="param-hint">{{ param.description }}</div>
          </el-form-item>
        </el-form>
      </div>
      <el-empty v-else-if="testTarget" description="该工具无需参数" :image-size="48" />

      <!-- Test result -->
      <div v-if="testResult !== null" class="test-result-section">
        <h4 class="section-subtitle">
          测试结果
          <el-tag
            size="small"
            :type="testError ? 'danger' : 'success'"
            effect="plain"
            style="margin-left: 8px"
          >
            {{ testError ? '失败' : '成功' }}
          </el-tag>
          <span v-if="testDuration !== null" class="test-duration">
            耗时 {{ testDuration }}ms
          </span>
        </h4>
        <div class="json-viewer">
          <pre><code>{{ formattedResult }}</code></pre>
        </div>
      </div>

      <template #footer>
        <el-button @click="testDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="executeTest">
          <el-icon style="margin-right: 4px"><CaretRight /></el-icon>
          执行测试
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<!-- ======================================================================= -->
<!--  Script Setup                                                           -->
<!-- ======================================================================= -->
<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh,
  CaretRight,
  Collection,
  User,
  Search,
  Connection,
  PictureFilled,
  Switch,
  Tools
} from '@element-plus/icons-vue'
import {
  listTools,
  updateTool,
  testTool
} from '@/api'

// ===========================================================================
//  Reactive State — Tools List
// ===========================================================================
const tools = ref([])
const loading = ref(false)
const refreshing = ref(false)

// ===========================================================================
//  Reactive State — Test Dialog
// ===========================================================================
const testDialogVisible = ref(false)
const testTarget = ref(null)
const testFormRef = ref(null)
const testForm = reactive({})
const testResult = ref(null)
const testError = ref(false)
const testDuration = ref(null)
const testing = ref(false)

// ===========================================================================
//  Reactive State — Last Execution Time
// ===========================================================================
const lastExecutionTime = ref(null)

// ===========================================================================
//  Computed — Stats
// ===========================================================================
const totalTools = computed(() => tools.value.length)

const enabledToolsCount = computed(() => {
  return tools.value.filter((t) => t.enabled !== false).length
})

const lastExecDisplay = computed(() => {
  if (!lastExecutionTime.value) return '暂无'
  const d = new Date(lastExecutionTime.value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})

const statCards = computed(() => [
  {
    key: 'totalTools',
    label: '工具总数',
    value: totalTools.value,
    icon: Tools
  },
  {
    key: 'enabledTools',
    label: '已启用工具',
    value: enabledToolsCount.value,
    icon: Switch
  },
  {
    key: 'lastExecution',
    label: '最近执行时间',
    value: lastExecDisplay.value,
    icon: CaretRight
  }
])

// ===========================================================================
//  Computed — Test Result Formatting
// ===========================================================================
const formattedResult = computed(() => {
  if (testResult.value === null || testResult.value === undefined) return ''
  try {
    return JSON.stringify(testResult.value, null, 2)
  } catch {
    return String(testResult.value)
  }
})

// ===========================================================================
//  Tool Icons
// ===========================================================================
const iconMap = {
  KnowledgeBase: Collection,
  CustomerMemory: User,
  ProductLookup: Search,
  WebSearch: Connection,
  ImageAnalysis: PictureFilled
}

const iconColorMap = {
  KnowledgeBase: '#409eff',
  CustomerMemory: '#67c23a',
  ProductLookup: '#e6a23c',
  WebSearch: '#909399',
  ImageAnalysis: '#f56c6c'
}

function toolIcon(name) {
  return iconMap[name] || Tools
}

function iconColor(row) {
  return iconColorMap[row.name] || '#409eff'
}

// ===========================================================================
//  Category Helpers
// ===========================================================================
function categoryTagType(category) {
  const map = {
    '知识管理': 'primary',
    '数据查询': 'success',
    '多媒体': 'warning'
  }
  return map[category] || 'info'
}

// ===========================================================================
//  Data Fetching
// ===========================================================================
async function fetchTools() {
  loading.value = true
  try {
    const data = await listTools()
    tools.value = data?.tools || (Array.isArray(data) ? data : [])
  } catch {
    // If API not available, use built-in defaults
    tools.value = getDefaultTools()
  } finally {
    loading.value = false
  }
}

async function refreshTools() {
  refreshing.value = true
  try {
    await fetchTools()
    ElMessage.success('工具列表已刷新')
  } catch {
    // error already shown by interceptor
  } finally {
    refreshing.value = false
  }
}

// ===========================================================================
//  Default Tools (fallback when API unavailable)
// ===========================================================================
function getDefaultTools() {
  return [
    {
      name: 'KnowledgeBase',
      displayName: '知识库检索',
      description: '检索知识库中的 FAQ、文档和已知解决方案，支持语义搜索和关键词匹配',
      category: '知识管理',
      enabled: true,
      parameters: [
        { name: 'query', type: 'string', required: true, description: '搜索查询语句' },
        { name: 'top_k', type: 'integer', required: false, description: '返回结果数量', default: 5 },
        { name: 'category', type: 'string', required: false, description: '按分类筛选' },
        { name: 'min_confidence', type: 'number', required: false, description: '最低置信度阈值', default: 0.6 }
      ]
    },
    {
      name: 'CustomerMemory',
      displayName: '客户记忆',
      description: '读取和更新客户的历史信息、偏好记录与上下文记忆，实现个性化服务',
      category: '知识管理',
      enabled: true,
      parameters: [
        { name: 'customer_id', type: 'string', required: true, description: '客户唯一标识' },
        { name: 'action', type: 'string', required: true, description: '操作类型: read / update / search' },
        { name: 'field', type: 'string', required: false, description: '要读取或更新的字段名' },
        { name: 'value', type: 'string', required: false, description: '更新时的字段值' }
      ]
    },
    {
      name: 'ProductLookup',
      displayName: '产品查询',
      description: '查询产品信息、库存状态、价格、促销活动等实时数据',
      category: '数据查询',
      enabled: true,
      parameters: [
        { name: 'query', type: 'string', required: true, description: '产品名称、SKU 或关键词' },
        { name: 'fields', type: 'string', required: false, description: '需要返回的字段列表，逗号分隔' },
        { name: 'in_stock_only', type: 'boolean', required: false, description: '仅显示有库存的产品', default: false }
      ]
    },
    {
      name: 'WebSearch',
      displayName: '网页搜索',
      description: '在互联网上搜索实时信息，获取最新资讯、文档和公开数据',
      category: '数据查询',
      enabled: true,
      parameters: [
        { name: 'query', type: 'string', required: true, description: '搜索关键词' },
        { name: 'num_results', type: 'integer', required: false, description: '返回结果数量', default: 10 },
        { name: 'language', type: 'string', required: false, description: '语言偏好，如 zh-CN', default: 'zh-CN' }
      ]
    },
    {
      name: 'ImageAnalysis',
      displayName: '图像分析',
      description: '分析用户上传的图片内容，识别物体、文字、场景，支持截图理解与商品识别',
      category: '多媒体',
      enabled: false,
      parameters: [
        { name: 'image_url', type: 'string', required: true, description: '图片 URL 地址' },
        { name: 'analysis_type', type: 'string', required: false, description: '分析类型: describe / ocr / object_detect', default: 'describe' },
        { name: 'detail_level', type: 'string', required: false, description: '详细程度: brief / standard / detailed', default: 'standard' }
      ]
    }
  ]
}

// ===========================================================================
//  Toggle Enabled
// ===========================================================================
async function toggleEnabled(row, value) {
  try {
    await updateTool(row.name, { enabled: value })
    row.enabled = value
    ElMessage.success(value ? '已启用' : '已禁用')
  } catch {
    // If API call fails, try to update in-memory
    row.enabled = value
    ElMessage.warning('状态已本地更新，后端同步可能失败')
  }
}

// ===========================================================================
//  Test Dialog
// ===========================================================================
function openTestDialog(row) {
  testTarget.value = row
  testResult.value = null
  testError.value = false
  testDuration.value = null

  // Reset test form with defaults or empty values
  const params = row.parameters || []
  for (const key of Object.keys(testForm)) {
    delete testForm[key]
  }
  for (const param of params) {
    if (param.default !== undefined) {
      testForm[param.name] = param.default
    } else if (param.type === 'boolean') {
      testForm[param.name] = false
    } else if (param.type === 'number' || param.type === 'integer') {
      testForm[param.name] = undefined
    } else {
      testForm[param.name] = ''
    }
  }

  testDialogVisible.value = true
}

async function executeTest() {
  if (!testTarget.value) return

  // Validate required params
  const params = testTarget.value.parameters || []
  const hasRequired = params.some((p) => p.required)
  if (hasRequired && testFormRef.value) {
    try {
      await testFormRef.value.validate()
    } catch {
      ElMessage.warning('请填写所有必填参数')
      return
    }
  }

  testing.value = true
  testResult.value = null
  testError.value = false
  testDuration.value = null

  const start = performance.now()

  try {
    // Build payload: only include non-empty values
    const payload = {}
    for (const key of Object.keys(testForm)) {
      const val = testForm[key]
      if (val !== '' && val !== undefined && val !== null) {
        payload[key] = val
      }
    }

    const result = await testTool(testTarget.value.name, payload)
    testResult.value = result
    testError.value = false
    lastExecutionTime.value = new Date().toISOString()
    ElMessage.success(`工具 "${testTarget.value.displayName || testTarget.value.name}" 测试通过`)
  } catch (err) {
    testResult.value = {
      error: true,
      message: err?.response?.data?.message || err?.message || '测试请求失败',
      timestamp: new Date().toISOString()
    }
    testError.value = true
  } finally {
    testDuration.value = Math.round(performance.now() - start)
    testing.value = false
  }
}

// ===========================================================================
//  Lifecycle
// ===========================================================================
onMounted(() => {
  fetchTools()
})
</script>

<!-- ======================================================================= -->
<!--  Scoped Styles                                                          -->
<!-- ======================================================================= -->
<style scoped>
.tools-config-page {
  max-width: 1400px;
}

/* ---- Header ---- */
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
}

/* ---- Stat Cards ---- */
.stat-row {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 8px;
}

.stat-card :deep(.el-card__body) {
  padding: 18px 22px;
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
  font-size: 26px;
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

/* ---- Table ---- */
.tools-table {
  margin-top: 0;
}

.tools-table .el-table__empty-text {
  color: #909399;
}

.tool-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-icon {
  flex-shrink: 0;
}

.tool-name-text {
  font-weight: 500;
  color: #303133;
}

.cell-text {
  color: #606266;
  font-size: 13px;
}

/* ---- Parameter Schema Popover ---- */
.params-schema {
  max-height: 360px;
  overflow-y: auto;
}

.params-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}

.param-item {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}

.param-item:last-child {
  border-bottom: none;
}

.param-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}

.param-name {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
  font-family: 'Menlo', 'Consolas', monospace;
}

.param-type {
  font-size: 12px;
  color: #909399;
  font-family: 'Menlo', 'Consolas', monospace;
}

.param-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.param-default {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.param-default code {
  background: #f5f7fa;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
  color: #e6a23c;
}

.params-empty {
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  padding: 16px 0;
}

/* ---- Test Dialog ---- */
.test-descriptions {
  margin-bottom: 16px;
}

.test-params-section {
  margin-bottom: 16px;
}

.section-subtitle {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 12px 0;
  display: flex;
  align-items: center;
}

.test-duration {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
  font-weight: 400;
}

.test-form {
  padding: 0;
}

.param-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
  margin-top: 2px;
}

/* ---- Test Result ---- */
.test-result-section {
  margin-top: 16px;
}

.json-viewer {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  max-height: 360px;
}

.json-viewer pre {
  margin: 0;
  padding: 0;
}

.json-viewer code {
  font-family: 'Menlo', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .stat-card :deep(.el-card__body) {
    padding: 14px 16px;
  }

  .stat-value {
    font-size: 22px;
  }
}
</style>
