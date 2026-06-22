import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: 'Dashboard', icon: 'DataAnalysis' }
  },
  {
    path: '/chat',
    name: 'LiveChat',
    component: () => import('@/views/LiveChat.vue'),
    meta: { title: 'Live Chat', icon: 'ChatDotRound' }
  },
  {
    path: '/knowledge',
    name: 'KnowledgeBase',
    component: () => import('@/views/KnowledgeBase.vue'),
    meta: { title: 'Knowledge Base', icon: 'Collection' }
  },
  {
    path: '/persona',
    name: 'PersonaEditor',
    component: () => import('@/views/PersonaEditor.vue'),
    meta: { title: 'Persona Editor', icon: 'UserFilled' }
  },
  {
    path: '/models',
    name: 'ModelConfig',
    component: () => import('@/views/ModelConfig.vue'),
    meta: { title: 'AI Models', icon: 'Cpu' }
  },
  {
    path: '/tools',
    name: 'ToolsConfig',
    component: () => import('@/views/ToolsConfig.vue'),
    meta: { title: 'Agent Tools', icon: 'Switch' }
  },
  {
    path: '/products',
    name: 'Products',
    component: () => import('@/views/Products.vue'),
    meta: { title: 'Products', icon: 'Goods' }
  },
  {
    path: '/analytics',
    name: 'Analytics',
    component: () => import('@/views/Analytics.vue'),
    meta: { title: 'Analytics', icon: 'TrendCharts' }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: 'Settings', icon: 'Setting' }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '404' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

// Global navigation guard — update document title
router.beforeEach((to, _from, next) => {
  const title = to.meta?.title
  document.title = title ? `${title} — Kefu AI` : 'Kefu AI 客服管理面板'
  next()
})

export default router
