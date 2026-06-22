import { defineStore } from 'pinia'
import { getStatus } from '@/api'

export const useAppStore = defineStore('app', {
  state: () => ({
    /** @type {Object|null} System status object from the backend */
    systemStatus: null,
    /** @type {string} Currently highlighted page id */
    activePage: 'dashboard',
    /** @type {boolean} Global loading indicator */
    loading: false,
    /** @type {Error|null} Last fetch error, for debugging */
    lastError: null
  }),

  getters: {
    isRunning: (state) => state.systemStatus?.running === true,
    adapterName: (state) => state.systemStatus?.adapter ?? null,
    uptime: (state) => state.systemStatus?.uptime ?? null
  },

  actions: {
    /**
     * Fetch current system status from the backend and update state.
     * Silently catches errors so the UI can degrade gracefully.
     */
    async fetchStatus() {
      this.loading = true
      this.lastError = null
      try {
        const data = await getStatus()
        this.systemStatus = data
      } catch (err) {
        this.lastError = err
        this.systemStatus = null
      } finally {
        this.loading = false
      }
    },

    /**
     * Update the active page identifier (used by sidebar highlighting).
     * @param {string} page
     */
    setPage(page) {
      this.activePage = page
    }
  }
})
