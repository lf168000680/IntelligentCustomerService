<template>
  <div class="app-container">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1 class="sidebar-title">AI 客服管理面板</h1>
      </div>

      <el-menu
        :default-active="activeMenu"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        class="sidebar-menu"
      >
        <el-menu-item index="/">
          <el-icon><DataAnalysis /></el-icon>
          <span>Dashboard</span>
        </el-menu-item>

        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>Live Chat</span>
        </el-menu-item>

        <el-menu-item index="/knowledge">
          <el-icon><Collection /></el-icon>
          <span>Knowledge Base</span>
        </el-menu-item>

        <el-menu-item index="/persona" class="persona-menu-item">
          <el-icon><UserFilled /></el-icon>
          <span>Persona Editor</span>
          <el-tag size="small" effect="dark" type="warning" class="core-tag">核心</el-tag>
        </el-menu-item>

        <el-menu-item index="/models">
          <el-icon><Cpu /></el-icon>
          <span>AI Models</span>
        </el-menu-item>

        <el-menu-item index="/tools">
          <el-icon><Switch /></el-icon>
          <span>Agent Tools</span>
        </el-menu-item>

        <el-menu-item index="/products">
          <el-icon><Goods /></el-icon>
          <span>Products</span>
        </el-menu-item>

        <el-menu-item index="/analytics">
          <el-icon><TrendCharts /></el-icon>
          <span>Analytics</span>
        </el-menu-item>

        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>Settings</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="system-status">
          <span
            class="status-dot"
            :class="statusClass"
          ></span>
          <span class="status-text">{{ statusLabel }}</span>
        </div>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const store = useAppStore()

const activeMenu = computed(() => route.path)

const statusClass = computed(() => {
  if (!store.systemStatus) return 'status-unknown'
  return store.systemStatus.running ? 'status-online' : 'status-offline'
})

const statusLabel = computed(() => {
  if (!store.systemStatus) return '检查中...'
  return store.systemStatus.running ? '系统运行中' : '系统离线'
})

onMounted(() => {
  store.fetchStatus()
})
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ---- Sidebar ---- */
.sidebar {
  display: flex;
  flex-direction: column;
  width: 220px;
  background-color: #304156;
  flex-shrink: 0;
  overflow-y: auto;
  user-select: none;
}

.sidebar-header {
  padding: 20px 16px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.sidebar-menu {
  flex: 1;
  border-right: none !important;
}

.sidebar-menu .el-menu-item {
  height: 48px;
  line-height: 48px;
  font-size: 14px;
}

.sidebar-menu .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.05) !important;
}

.sidebar-menu .el-menu-item.is-active {
  background-color: rgba(64, 158, 255, 0.15) !important;
}

/* Persona highlight */
.persona-menu-item {
  position: relative;
}

.core-tag {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
}

/* Sidebar footer */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.system-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #bfcbd9;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-online {
  background-color: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.6);
}

.status-offline {
  background-color: #f56c6c;
  box-shadow: 0 0 6px rgba(245, 108, 108, 0.6);
}

.status-unknown {
  background-color: #909399;
}

/* ---- Main ---- */
.main-content {
  flex: 1;
  overflow-y: auto;
  background-color: #f0f2f5;
  padding: 20px;
}

/* ---- Route transition ---- */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
