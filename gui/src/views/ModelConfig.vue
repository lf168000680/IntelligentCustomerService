<template>
  <div class="model-config-page">
    <!-- Header -->
    <div class="page-header">
      <h2 class="page-title">AI 模型配置</h2>
      <div class="page-actions">
        <el-button @click="refreshStatus" :loading="refreshing" :icon="Refresh">
          刷新状态
        </el-button>
        <el-button type="primary" @click="openAddDialog" :icon="Plus">
          添加模型
        </el-button>
      </div>
    </div>

    <!-- Model Table -->
    <el-table
      :data="models"
      stripe
      border
      v-loading="loading"
      empty-text="暂无模型配置，请点击「添加模型」创建"
      class="model-table"
    >
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="提供商" width="150">
        <template #default="{ row }">
          <el-tag :type="providerTagType(row.provider)" effect="light" size="small">
            {{ providerLabel(row.provider) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="model_id" label="模型 ID" min-width="180" show-overflow-tooltip />
      <el-table-column prop="api_base" label="API Base" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.api_base">{{ row.api_base }}</span>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="temperature" label="温度" width="90" align="center" />
      <el-table-column prop="max_tokens" label="最大 Token" width="110" align="center" />
      <el-table-column label="标签" width="200">
        <template #default="{ row }">
          <el-tag
            v-for="tag in row.tags"
            :key="tag"
            size="small"
            class="tag-item"
          >
            {{ tagLabel(tag) }}
          </el-tag>
          <span v-if="!row.tags || row.tags.length === 0" class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(val) => toggleEnabled(row, val)"
            size="small"
          />
        </template>
      </el-table-column>
      <el-table-column label="健康" width="80" align="center">
        <template #default="{ row }">
          <span
            class="health-dot"
            :class="healthClass(row)"
            :title="healthStatus(row)"
          ></span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="openEditDialog(row)">
            编辑
          </el-button>
          <el-button type="warning" link size="small" @click="handleTest(row)">
            测试
          </el-button>
          <el-popconfirm
            title="确定要删除该模型吗？"
            confirm-button-text="删除"
            cancel-button-text="取消"
            confirm-button-type="danger"
            @confirm="handleDelete(row)"
          >
            <template #reference>
              <el-button type="danger" link size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- Add / Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑模型' : '添加模型'"
      width="580px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="110px"
        label-position="right"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：claude-sonnet" />
        </el-form-item>

        <el-form-item label="提供商" prop="provider">
          <el-select v-model="form.provider" placeholder="请选择提供商" style="width: 100%">
            <el-option label="Anthropic" value="anthropic" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="OpenAI Compatible" value="openai_compat" />
            <el-option label="Custom/Relay (自定义)" value="custom_relay" />
          </el-select>
        </el-form-item>

        <!-- Presets for custom relay -->
        <el-form-item v-if="form.provider === 'custom_relay'" label="快捷预设">
          <div class="preset-buttons">
            <el-button size="small" type="primary" plain @click="applyPreset('openrouter')">OpenRouter</el-button>
            <el-button size="small" type="primary" plain @click="applyPreset('api2d')">API2D</el-button>
            <el-button size="small" type="primary" plain @click="applyPreset('oneapi')">OneAPI</el-button>
            <el-button size="small" type="warning" plain @click="applyPreset('custom')">自定义中转站</el-button>
          </div>
        </el-form-item>

        <el-form-item label="模型 ID" prop="model_id">
          <el-input v-model="form.model_id" placeholder="例如：claude-sonnet-4-6 或 gpt-4o" />
        </el-form-item>

        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            placeholder="输入 API Key"
          />
        </el-form-item>

        <el-form-item v-if="form.provider === 'openai_compat' || form.provider === 'custom_relay'" label="API Base" prop="api_base">
          <el-input v-model="form.api_base" placeholder="例如：https://api.example.com/v1" />
        </el-form-item>

        <el-form-item v-if="form.provider === 'custom_relay'" label="Custom Headers">
          <el-input
            v-model="form.headers"
            type="textarea"
            :rows="3"
            placeholder='JSON 格式，例如：{"X-Custom-Header": "value"}'
          />
        </el-form-item>

        <el-form-item v-if="form.provider === 'custom_relay'" label="Extra Config">
          <el-input
            v-model="form.extra_config"
            type="textarea"
            :rows="3"
            placeholder='JSON 格式，例如：{"timeout": 60}'
          />
        </el-form-item>

        <el-form-item label="温度">
          <div class="slider-row">
            <el-slider
              v-model="form.temperature"
              :min="0"
              :max="1"
              :step="0.1"
              show-input
              :format-tooltip="(v) => v.toFixed(1)"
              style="flex: 1"
            />
          </div>
        </el-form-item>

        <el-form-item label="最大 Token" prop="max_tokens">
          <el-input-number
            v-model="form.max_tokens"
            :min="1"
            :max="200000"
            :step="100"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="权重" prop="weight">
          <el-input-number
            v-model="form.weight"
            :min="1"
            :max="1000"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="标签">
          <el-checkbox-group v-model="form.tags">
            <el-checkbox label="default">默认</el-checkbox>
            <el-checkbox label="reasoning">推理</el-checkbox>
            <el-checkbox label="cheap">廉价</el-checkbox>
            <el-checkbox label="fast">快速</el-checkbox>
            <el-checkbox label="quality">优质</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ isEditing ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  listModels,
  addModel,
  updateModel,
  deleteModel,
  testModel,
  getModelsStatus
} from '@/api'

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const models = ref([])
const loading = ref(false)
const refreshing = ref(false)
const submitting = ref(false)

// Status map: keyed by model name, value = status object from backend
const statusMap = ref({})

// Dialog
const dialogVisible = ref(false)
const isEditing = ref(false)
const editingName = ref('')
const formRef = ref(null)

const defaultForm = () => ({
  name: '',
  provider: 'anthropic',
  model_id: '',
  api_key: '',
  api_base: '',
  headers: '',
  extra_config: '',
  temperature: 0.7,
  max_tokens: 4096,
  weight: 100,
  tags: [],
  enabled: true
})

const form = reactive(defaultForm())

const formRules = {
  name: [
    { required: true, message: '请输入模型名称', trigger: 'blur' }
  ],
  provider: [
    { required: true, message: '请选择提供商', trigger: 'change' }
  ],
  model_id: [
    { required: true, message: '请输入模型 ID', trigger: 'blur' }
  ],
  api_key: [
    { required: true, message: '请输入 API Key', trigger: 'blur' }
  ]
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchModels() {
  loading.value = true
  try {
    const data = await listModels()
    models.value = data?.models || []
  } catch {
    models.value = []
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  refreshing.value = true
  try {
    const statuses = await getModelsStatus()
    // statuses expected as array of { name, healthy, ... }
    const map = {}
    if (Array.isArray(statuses)) {
      for (const s of statuses) {
        map[s.name] = s
      }
    }
    statusMap.value = map
    ElMessage.success('状态已刷新')
  } catch {
    // error already shown by interceptor
  } finally {
    refreshing.value = false
  }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------
function providerTagType(provider) {
  const map = {
    anthropic: '',
    openai: 'success',
    openai_compat: 'warning',
    custom_relay: 'danger'
  }
  return map[provider] || 'info'
}

function providerLabel(provider) {
  const map = {
    anthropic: 'Anthropic',
    openai: 'OpenAI',
    openai_compat: 'OpenAI Compatible',
    custom_relay: 'Custom/Relay'
  }
  return map[provider] || provider
}

function tagLabel(tag) {
  const map = {
    default: '默认',
    reasoning: '推理',
    cheap: '廉价',
    fast: '快速',
    quality: '优质'
  }
  return map[tag] || tag
}

// ---------------------------------------------------------------------------
// Presets for custom relay providers
// ---------------------------------------------------------------------------
const PRESETS = {
  openrouter: {
    api_base: 'https://openrouter.ai/api/v1',
    headers: '',
    extra_config: ''
  },
  api2d: {
    api_base: 'https://openai.api2d.net',
    headers: '',
    extra_config: ''
  },
  oneapi: {
    api_base: 'https://api.oneapi.com/v1',
    headers: '',
    extra_config: ''
  },
  custom: {
    api_base: '',
    headers: '',
    extra_config: ''
  }
}

function applyPreset(presetKey) {
  const preset = PRESETS[presetKey]
  if (!preset) return
  form.api_base = preset.api_base
  form.headers = preset.headers
  form.extra_config = preset.extra_config
  if (presetKey === 'custom') {
    ElMessage.info('请手动填写中转站 API Base、Headers 等配置')
  } else {
    ElMessage.success(`已应用 ${presetKey} 预设`)
  }
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
function healthClass(row) {
  const s = statusMap.value[row.name]
  if (!s) return 'health-unknown'
  return s.healthy ? 'health-ok' : 'health-bad'
}

function healthStatus(row) {
  const s = statusMap.value[row.name]
  if (!s) return '未知'
  return s.healthy ? '健康' : (s.error || '异常')
}

// ---------------------------------------------------------------------------
// Dialog helpers
// ---------------------------------------------------------------------------
function openAddDialog() {
  isEditing.value = false
  editingName.value = ''
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEditing.value = true
  editingName.value = row.name
  Object.assign(form, {
    name: row.name ?? '',
    provider: row.provider ?? 'anthropic',
    model_id: row.model_id ?? '',
    api_key: row.api_key ?? '',
    api_base: row.api_base ?? '',
    headers: row.headers ?? '',
    extra_config: row.extra_config ?? '',
    temperature: row.temperature ?? 0.7,
    max_tokens: row.max_tokens ?? 4096,
    weight: row.weight ?? 100,
    tags: Array.isArray(row.tags) ? [...row.tags] : [],
    enabled: row.enabled !== false
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = { ...form }
    if (!payload.api_key.startsWith('****')) {
      // keep the raw value as entered
    }
    if (payload.provider !== 'openai_compat' && payload.provider !== 'custom_relay') {
      delete payload.api_base
    }
    if (payload.provider !== 'custom_relay') {
      delete payload.headers
      delete payload.extra_config
    }

    if (isEditing.value) {
      await updateModel(editingName.value, payload)
      ElMessage.success('模型已更新')
    } else {
      await addModel(payload)
      ElMessage.success('模型已添加')
    }

    dialogVisible.value = false
    await fetchModels()
    await refreshStatus()
  } catch {
    // error already shown by interceptor
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------
async function toggleEnabled(row, value) {
  try {
    await updateModel(row.name, { enabled: value })
    row.enabled = value
    ElMessage.success(value ? '已启用' : '已禁用')
  } catch {
    // revert is not needed; the switch is model-value bound
  }
}

async function handleTest(row) {
  try {
    const result = await testModel(row.name)
    ElMessage.success({
      message: `模型 "${row.name}" 测试通过`,
      duration: 3000
    })
    if (result) {
      console.log('Test result:', result)
    }
  } catch {
    // error already shown by interceptor
  }
}

async function handleDelete(row) {
  try {
    await deleteModel(row.name)
    ElMessage.success('模型已删除')
    await fetchModels()
  } catch {
    // error already shown by interceptor
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  await Promise.all([fetchModels(), refreshStatus()])
})
</script>

<style scoped>
.model-config-page {
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

/* ---- Table ---- */
.model-table {
  margin-top: 0;
}

.model-table .el-table__empty-text {
  color: #909399;
}

.tag-item {
  margin-right: 4px;
  margin-bottom: 2px;
}

.text-muted {
  color: #c0c4cc;
}

/* ---- Health dot ---- */
.health-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.health-ok {
  background-color: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
}

.health-bad {
  background-color: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.5);
}

.health-unknown {
  background-color: #c0c4cc;
}

/* ---- Slider ---- */
.slider-row {
  display: flex;
  align-items: center;
  width: 100%;
}

/* ---- Preset buttons ---- */
.preset-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
