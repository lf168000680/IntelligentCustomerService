<template>
  <div class="knowledge-base">
    <!-- ================================================================== -->
    <!--  Page Header                                                       -->
    <!-- ================================================================== -->
    <div class="page-header flex-between">
      <div>
        <h2>知识库管理</h2>
        <p class="subtitle">管理客服知识条目、审核自动学习内容、查看知识缺口</p>
      </div>
    </div>

    <!-- ================================================================== -->
    <!--  Top Bar: Search + Filter + Actions                                -->
    <!-- ================================================================== -->
    <div class="card-container toolbar">
      <div class="toolbar-left">
        <el-input
          v-model="searchQuery"
          placeholder="搜索问题或答案..."
          :prefix-icon="Search"
          clearable
          style="width: 280px"
          @clear="fetchKnowledge"
          @keyup.enter="fetchKnowledge"
        />
        <el-select
          v-model="categoryFilter"
          placeholder="按分类筛选"
          clearable
          style="width: 180px; margin-left: 12px"
          @change="fetchKnowledge"
        >
          <el-option
            v-for="cat in allCategories"
            :key="cat"
            :label="cat"
            :value="cat"
          />
        </el-select>
        <el-select
          v-model="statusFilter"
          placeholder="按状态筛选"
          clearable
          style="width: 140px; margin-left: 12px"
          @change="fetchKnowledge"
        >
          <el-option label="启用" value="active" />
          <el-option label="待审核" value="pending" />
          <el-option label="已归档" value="archived" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" :icon="Plus" @click="openAddDialog">
          添加知识
        </el-button>
        <el-button
          type="warning"
          :icon="Refresh"
          :loading="learningLoading"
          @click="handleLearn"
        >
          触发学习
        </el-button>
      </div>
    </div>

    <!-- ================================================================== -->
    <!--  Main Knowledge Table                                              -->
    <!-- ================================================================== -->
    <div class="card-container" style="margin-top: 16px">
      <el-table
        v-loading="loading"
        :data="knowledgeList"
        stripe
        border
        style="width: 100%"
        row-key="id"
      >
        <el-table-column type="index" label="#" width="50" align="center" />

        <el-table-column label="问题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tooltip
              :content="row.question"
              placement="top"
              :show-after="400"
              effect="dark"
            >
              <span class="cell-text">{{ row.question }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="答案" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tooltip
              :content="row.answer"
              placement="top"
              :show-after="400"
              effect="dark"
            >
              <span class="cell-text">{{ row.answer }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="分类" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" round>
              {{ row.category || '未分类' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.source === 'manual' ? '' : 'warning'"
              effect="plain"
              round
            >
              {{ row.source === 'manual' ? '人工' : '自动' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="使用次数" width="90" align="center">
          <template #default="{ row }">
            <span>{{ row.usage_count ?? row.usageCount ?? 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="置信度" width="130" align="center">
          <template #default="{ row }">
            <template v-if="row.source === 'auto_learned'">
              <el-progress
                :percentage="Math.round((row.confidence ?? 0) * 100)"
                :stroke-width="6"
                :show-text="true"
                :status="confidenceStatus(row.confidence)"
              />
            </template>
            <template v-else>
              <span class="text-muted" style="font-size: 12px">—</span>
            </template>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="statusTagType(row.status)"
              effect="plain"
              round
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :icon="Edit"
              @click="openEditDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              link
              type="danger"
              size="small"
              :icon="Delete"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="fetchKnowledge"
          @current-change="fetchKnowledge"
        />
      </div>
    </div>

    <!-- ================================================================== -->
    <!--  Add / Edit Dialog                                                 -->
    <!-- ================================================================== -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'add' ? '添加知识' : '编辑知识'"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="80px"
        label-position="right"
      >
        <el-form-item label="问题" prop="question">
          <el-input
            v-model="form.question"
            type="textarea"
            :rows="3"
            placeholder="请输入常见问题"
          />
        </el-form-item>

        <el-form-item label="答案" prop="answer">
          <el-input
            v-model="form.answer"
            type="textarea"
            :rows="6"
            placeholder="请输入标准答案"
          />
        </el-form-item>

        <el-form-item label="分类" prop="category">
          <el-input
            v-model="form.category"
            placeholder="请输入分类名称"
            clearable
          />
        </el-form-item>

        <el-form-item label="标签" prop="tags">
          <el-select
            v-model="form.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择或创建标签"
            style="width: 100%"
          >
            <el-option
              v-for="tag in knownTags"
              :key="tag"
              :label="tag"
              :value="tag"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-if="dialogMode === 'edit'" label="状态" prop="status">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="启用" value="active" />
            <el-option label="待审核" value="pending" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formLoading" @click="handleSave">
          {{ dialogMode === 'add' ? '添加' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ================================================================== -->
    <!--  Reject Reason Dialog                                              -->
    <!-- ================================================================== -->
    <el-dialog
      v-model="rejectDialogVisible"
      title="拒绝原因"
      width="480px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-input
        v-model="rejectReason"
        type="textarea"
        :rows="3"
        placeholder="请输入拒绝原因（可选）"
      />
      <template #footer>
        <el-button @click="rejectDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="confirmReject">确认拒绝</el-button>
      </template>
    </el-dialog>

    <!-- ================================================================== -->
    <!--  Learning Result Dialog                                            -->
    <!-- ================================================================== -->
    <el-dialog
      v-model="learnResultVisible"
      title="学习结果"
      width="500px"
      :close-on-click-modal="false"
    >
      <div v-if="learnResult" class="learn-result">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="新增条目">
            {{ learnResult.new_entries ?? learnResult.newEntries ?? 0 }}
          </el-descriptions-item>
          <el-descriptions-item label="更新条目">
            {{ learnResult.updated_entries ?? learnResult.updatedEntries ?? 0 }}
          </el-descriptions-item>
          <el-descriptions-item label="新缺口">
            {{ learnResult.new_gaps ?? learnResult.newGaps ?? 0 }}
          </el-descriptions-item>
          <el-descriptions-item v-if="learnResult.message" label="详情">
            {{ learnResult.message }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button type="primary" @click="learnResultVisible = false">确定</el-button>
      </template>
    </el-dialog>

    <!-- ================================================================== -->
    <!--  自动学习审核队列 (Collapsible)                                      -->
    <!-- ================================================================== -->
    <el-collapse v-model="activeCollapse" class="collapse-section" style="margin-top: 20px">
      <el-collapse-item name="review">
        <template #title>
          <div class="collapse-title">
            <el-icon><WarningFilled /></el-icon>
            <span>自动学习审核队列</span>
            <el-badge
              v-if="reviewQueue.length"
              :value="reviewQueue.length"
              type="warning"
              class="collapse-badge"
            />
          </div>
        </template>

        <el-table
          v-loading="reviewLoading"
          :data="reviewQueue"
          stripe
          border
          style="width: 100%"
          row-key="id"
          empty-text="暂无待审核条目"
        >
          <el-table-column type="index" label="#" width="50" align="center" />

          <el-table-column label="问题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tooltip
                :content="row.question"
                placement="top"
                :show-after="400"
                effect="dark"
              >
                <span class="cell-text">{{ row.question }}</span>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="建议答案" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tooltip
                :content="row.proposed_answer ?? row.answer"
                placement="top"
                :show-after="400"
                effect="dark"
              >
                <span class="cell-text">{{ row.proposed_answer ?? row.answer }}</span>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="置信度" width="110" align="center">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.round((row.confidence ?? 0) * 100)"
                :stroke-width="6"
                :status="confidenceStatus(row.confidence)"
              />
            </template>
          </el-table-column>

          <el-table-column label="支持数" width="80" align="center">
            <template #default="{ row }">
              <span>{{ row.supporting_count ?? row.supportingCount ?? row.support_count ?? 0 }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="180" align="center" fixed="right">
            <template #default="{ row }">
              <el-button
                type="success"
                size="small"
                :icon="Select"
                @click="handleApprove(row.id)"
              >
                通过
              </el-button>
              <el-button
                type="danger"
                size="small"
                :icon="CloseBold"
                @click="handleRejectClick(row.id)"
              >
                拒绝
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- ================================================================ -->
      <!--  知识缺口                                                          -->
      <!-- ================================================================ -->
      <el-collapse-item name="gaps">
        <template #title>
          <div class="collapse-title">
            <el-icon><Warning /></el-icon>
            <span>知识缺口</span>
            <el-badge
              v-if="gaps.length"
              :value="gaps.length"
              type="danger"
              class="collapse-badge"
            />
          </div>
        </template>

        <div v-if="gaps.length === 0" class="empty-hint">
          暂无知识缺口
        </div>
        <div v-else class="gaps-list">
          <div
            v-for="(gap, idx) in gaps"
            :key="idx"
            class="gap-item"
          >
            <div class="gap-index">{{ idx + 1 }}</div>
            <div class="gap-body">
              <div class="gap-question">{{ gap.question ?? gap.query ?? gap.text }}</div>
              <div class="gap-meta">
                <el-tag size="small" type="danger" effect="plain" round>
                  频率: {{ gap.frequency ?? gap.freq ?? gap.count ?? 1 }}
                </el-tag>
                <span v-if="gap.last_seen ?? gap.lastSeen" class="text-muted">
                  最近出现: {{ gap.last_seen ?? gap.lastSeen }}
                </span>
              </div>
            </div>
            <el-button
              size="small"
              type="primary"
              :icon="Plus"
              @click="gapToKnowledge(idx)"
            >
              转为知识
            </el-button>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<!-- ======================================================================= -->
<!--  Script Setup                                                           -->
<!-- ======================================================================= -->
<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search,
  Plus,
  Refresh,
  Edit,
  Delete,
  Select,
  CloseBold,
  WarningFilled,
  Warning
} from '@element-plus/icons-vue'
import {
  listKnowledge,
  createKnowledge,
  updateKnowledge,
  deleteKnowledge,
  getReviewQueue,
  approveReview,
  rejectReview,
  triggerLearning
} from '@/api'

// =========================================================================
//  Reactive State — Knowledge List
// =========================================================================
const searchQuery = ref('')
const categoryFilter = ref('')
const statusFilter = ref('')
const knowledgeList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)

// =========================================================================
//  Reactive State — Add / Edit Dialog
// =========================================================================
const dialogVisible = ref(false)
const dialogMode = ref('add') // 'add' | 'edit'
const formRef = ref(null)
const formLoading = ref(false)
const form = reactive({
  id: null,
  question: '',
  answer: '',
  category: '',
  tags: [],
  status: 'active'
})

// =========================================================================
//  Reactive State — Review Queue
// =========================================================================
const reviewQueue = ref([])
const reviewLoading = ref(false)

// =========================================================================
//  Reactive State — Reject Dialog
// =========================================================================
const rejectDialogVisible = ref(false)
const rejectReviewId = ref(null)
const rejectReason = ref('')

// =========================================================================
//  Reactive State — Learning
// =========================================================================
const learningLoading = ref(false)
const learnResultVisible = ref(false)
const learnResult = ref(null)

// =========================================================================
//  Reactive State — Gaps
// =========================================================================
const gaps = ref([])
const activeCollapse = ref([])

// =========================================================================
//  Computed
// =========================================================================
const allCategories = computed(() => {
  const set = new Set()
  knowledgeList.value.forEach((item) => {
    if (item.category) set.add(item.category)
  })
  return Array.from(set).sort()
})

const knownTags = computed(() => {
  const set = new Set()
  knowledgeList.value.forEach((item) => {
    if (Array.isArray(item.tags)) {
      item.tags.forEach((t) => set.add(t))
    }
  })
  return Array.from(set).sort()
})

const formRules = {
  question: [{ required: true, message: '请输入问题', trigger: 'blur' }],
  answer: [{ required: true, message: '请输入答案', trigger: 'blur' }],
  category: [{ required: true, message: '请输入分类', trigger: 'blur' }]
}

// =========================================================================
//  Helpers
// =========================================================================
function statusTagType(status) {
  if (status === 'active') return 'success'
  if (status === 'pending') return 'warning'
  if (status === 'archived') return 'info'
  return ''
}

function statusLabel(status) {
  if (status === 'active') return '启用'
  if (status === 'pending') return '待审核'
  if (status === 'archived') return '已归档'
  return status || '未知'
}

function confidenceStatus(val) {
  const pct = (val ?? 0) * 100
  if (pct >= 80) return 'success'
  if (pct >= 50) return 'warning'
  return 'exception'
}

function resetForm() {
  form.id = null
  form.question = ''
  form.answer = ''
  form.category = ''
  form.tags = []
  form.status = 'active'
  nextTick(() => {
    formRef.value?.clearValidate()
  })
}

// =========================================================================
//  API Calls
// =========================================================================
async function fetchKnowledge() {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (searchQuery.value) params.search = searchQuery.value
    if (categoryFilter.value) params.category = categoryFilter.value
    if (statusFilter.value) params.status = statusFilter.value

    const data = await listKnowledge(params)
    // Handle different response shapes
    if (Array.isArray(data)) {
      knowledgeList.value = data
      total.value = data.length
    } else if (data && Array.isArray(data.list)) {
      knowledgeList.value = data.list
      total.value = data.total ?? data.list.length
    } else if (data && Array.isArray(data.items)) {
      knowledgeList.value = data.items
      total.value = data.total ?? data.items.length
    } else if (data && Array.isArray(data.data)) {
      knowledgeList.value = data.data
      total.value = data.total ?? data.data.length
    } else {
      knowledgeList.value = data ?? []
      total.value = Array.isArray(data) ? data.length : 0
    }
  } catch {
    // Error already shown by interceptor
  } finally {
    loading.value = false
  }
}

async function fetchReviewQueue() {
  reviewLoading.value = true
  try {
    const data = await getReviewQueue()
    // Handle different response shapes
    if (Array.isArray(data)) {
      reviewQueue.value = data
    } else if (data && Array.isArray(data.list)) {
      reviewQueue.value = data.list
    } else if (data && Array.isArray(data.items)) {
      reviewQueue.value = data.items
    } else if (data && Array.isArray(data.data)) {
      reviewQueue.value = data.data
    } else {
      reviewQueue.value = data ?? []
    }
  } catch {
    // Error already shown by interceptor
  } finally {
    reviewLoading.value = false
  }
}

async function fetchGaps() {
  try {
    const resp = await fetch('/api/knowledge/gaps')
    const body = await resp.json()
    // Handle wrapped response { code, data, message }
    let payload = body
    if (body && typeof body === 'object' && 'code' in body) {
      payload = body.data !== undefined ? body.data : body
    }
    if (Array.isArray(payload)) {
      gaps.value = payload
    } else if (payload && Array.isArray(payload.list)) {
      gaps.value = payload.list
    } else if (payload && Array.isArray(payload.items)) {
      gaps.value = payload.items
    } else {
      gaps.value = payload ?? []
    }
  } catch {
    // Silently fail — gaps are secondary information
    gaps.value = []
  }
}

// =========================================================================
//  Dialog: Add / Edit
// =========================================================================
function openAddDialog() {
  dialogMode.value = 'add'
  resetForm()
  dialogVisible.value = true
}

function openEditDialog(row) {
  dialogMode.value = 'edit'
  form.id = row.id
  form.question = row.question ?? ''
  form.answer = row.answer ?? ''
  form.category = row.category ?? ''
  form.tags = Array.isArray(row.tags) ? [...row.tags] : []
  form.status = row.status ?? 'active'
  dialogVisible.value = true
  nextTick(() => {
    formRef.value?.clearValidate()
  })
}

async function handleSave() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  formLoading.value = true
  try {
    const payload = {
      question: form.question,
      answer: form.answer,
      category: form.category,
      tags: form.tags,
      status: form.status
    }

    if (dialogMode.value === 'add') {
      await createKnowledge(payload)
      ElMessage.success('知识条目添加成功')
    } else {
      await updateKnowledge(form.id, payload)
      ElMessage.success('知识条目更新成功')
    }

    dialogVisible.value = false
    await fetchKnowledge()
  } catch {
    // Error already shown by interceptor
  } finally {
    formLoading.value = false
  }
}

// =========================================================================
//  Delete
// =========================================================================
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除该知识条目吗？`,
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return // cancelled
  }

  try {
    await deleteKnowledge(row.id)
    ElMessage.success('知识条目已删除')
    await fetchKnowledge()
  } catch {
    // Error already shown by interceptor
  }
}

// =========================================================================
//  Review: Approve / Reject
// =========================================================================
async function handleApprove(id) {
  try {
    await approveReview(id)
    ElMessage.success('审核已通过')
    await fetchReviewQueue()
  } catch {
    // Error already shown by interceptor
  }
}

function handleRejectClick(id) {
  rejectReviewId.value = id
  rejectReason.value = ''
  rejectDialogVisible.value = true
}

async function confirmReject() {
  if (!rejectReviewId.value) return
  try {
    await rejectReview(rejectReviewId.value, {
      reason: rejectReason.value || undefined
    })
    ElMessage.success('已拒绝该条目')
    rejectDialogVisible.value = false
    await fetchReviewQueue()
  } catch {
    // Error already shown by interceptor
  }
}

// =========================================================================
//  Trigger Learning
// =========================================================================
async function handleLearn() {
  learningLoading.value = true
  try {
    const result = await triggerLearning({ days_back: 1 })
    learnResult.value = result
    learnResultVisible.value = true
    ElMessage.success('自动学习完成')
    // Refresh related data
    await Promise.all([fetchKnowledge(), fetchReviewQueue(), fetchGaps()])
  } catch {
    // Error already shown by interceptor
  } finally {
    learningLoading.value = false
  }
}

// =========================================================================
//  Gap → Knowledge shortcut
// =========================================================================
function gapToKnowledge(idx) {
  const gap = gaps.value[idx]
  if (!gap) return
  dialogMode.value = 'add'
  resetForm()
  form.question = gap.question ?? gap.query ?? gap.text ?? ''
  form.category = gap.category ?? ''
  dialogVisible.value = true
}

// =========================================================================
//  Lifecycle
// =========================================================================
onMounted(() => {
  fetchKnowledge()
  fetchReviewQueue()
  fetchGaps()
})
</script>

<!-- ======================================================================= -->
<!--  Scoped Styles                                                          -->
<!-- ======================================================================= -->
<style scoped>
/* ---- Toolbar ---- */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ---- Table cell text ---- */
.cell-text {
  display: inline-block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

/* ---- Pagination ---- */
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* ---- Collapse sections ---- */
.collapse-section {
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.collapse-section :deep(.el-collapse-item__header) {
  font-size: 15px;
  font-weight: 600;
  padding: 0 20px;
  height: 50px;
  background-color: #fafafa;
  border-bottom: 1px solid #ebeef5;
}

.collapse-section :deep(.el-collapse-item__wrap) {
  padding: 0;
}

.collapse-section :deep(.el-collapse-item__content) {
  padding: 16px 20px;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.collapse-badge {
  margin-left: 8px;
}

/* ---- Gaps list ---- */
.empty-hint {
  text-align: center;
  color: #909399;
  padding: 32px 0;
  font-size: 14px;
}

.gaps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gap-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fafafa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  transition: background 0.2s;
}

.gap-item:hover {
  background: #f0f2f5;
}

.gap-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #f56c6c;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.gap-body {
  flex: 1;
  min-width: 0;
}

.gap-question {
  font-size: 14px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gap-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
}

/* ---- Learn result dialog ---- */
.learn-result :deep(.el-descriptions__label) {
  width: 100px;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-left {
    flex-direction: column;
    gap: 10px;
  }

  .toolbar-left .el-input,
  .toolbar-left .el-select {
    width: 100% !important;
    margin-left: 0 !important;
  }

  .toolbar-right {
    justify-content: flex-end;
  }
}
</style>
