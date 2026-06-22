<template>
  <div class="products-page">
    <!-- Header -->
    <div class="page-header">
      <h2 class="page-title">商品管理</h2>
      <div class="page-actions">
        <el-button type="primary" :icon="Refresh" :loading="syncing" @click="handleSync">
          手动同步
        </el-button>
      </div>
    </div>

    <!-- Info Banner -->
    <el-alert
      title="商品信息自动从淘宝/抖音平台同步"
      type="info"
      :closable="false"
      show-icon
      class="info-banner"
    />

    <!-- Product Table -->
    <el-table
      :data="products"
      stripe
      border
      v-loading="loading"
      empty-text="暂无商品数据，启动适配器后将自动同步"
      class="product-table"
    >
      <el-table-column label="商品图片" width="100" align="center">
        <template #default="{ row }">
          <el-image
            v-if="row.image"
            :src="row.image"
            :preview-src-list="[row.image]"
            fit="cover"
            style="width: 60px; height: 60px; border-radius: 4px"
          />
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>

      <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />

      <el-table-column label="价格" width="120" align="right">
        <template #default="{ row }">
          <span class="price-text">&yen;{{ formatPrice(row.price) }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="stock" label="库存" width="90" align="center" />

      <el-table-column prop="sku" label="SKU" width="140" show-overflow-tooltip />

      <el-table-column label="平台" width="110" align="center">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="platformTagType(row.platform)"
            effect="plain"
          >
            {{ row.platform || '未知' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="最后同步时间" width="180" align="center">
        <template #default="{ row }">
          <span>{{ row.lastSyncTime || '未同步' }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------
const products = ref([])
const loading = ref(false)
const syncing = ref(false)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatPrice(val) {
  if (val == null) return '0.00'
  const num = Number(val)
  return Number.isNaN(num) ? '0.00' : num.toFixed(2)
}

function platformTagType(platform) {
  if (platform === '淘宝') return 'danger'
  if (platform === '抖音') return ''
  if (platform === '京东') return 'danger'
  if (platform === '拼多多') return 'danger'
  return 'info'
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function handleSync() {
  syncing.value = true
  try {
    // TODO: Connect to actual sync API
    await new Promise((resolve) => setTimeout(resolve, 1500))
    ElMessage.success('同步完成')
  } catch {
    ElMessage.error('同步失败，请检查适配器状态')
  } finally {
    syncing.value = false
  }
}
</script>

<style scoped>
.products-page {
  max-width: 1400px;
}

/* ---- Header ---- */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
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

/* ---- Info Banner ---- */
.info-banner {
  margin-bottom: 20px;
  border-radius: 8px;
}

/* ---- Table ---- */
.product-table {
  margin-top: 0;
}

.product-table :deep(.el-table__empty-text) {
  color: #909399;
}

.price-text {
  font-weight: 500;
  color: #f56c6c;
}

.text-muted {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
