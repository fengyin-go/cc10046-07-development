import { createRouter, createWebHistory } from 'vue-router'

import BackfillView from '@/views/BackfillView.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/backfill', name: 'backfill', component: BackfillView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
