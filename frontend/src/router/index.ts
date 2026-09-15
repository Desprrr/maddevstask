import { createRouter, createWebHistory } from 'vue-router'
import CheckDetailView from '../views/CheckDetailView.vue'
import DashboardView from '../views/DashboardView.vue'
import PublicStatusView from '../views/PublicStatusView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/checks/:id', name: 'check-detail', component: CheckDetailView, props: true },
    { path: '/status', name: 'public-status', component: PublicStatusView },
  ],
})
