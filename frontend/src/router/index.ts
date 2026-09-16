import { createRouter, createWebHistory } from 'vue-router'
import CheckDetailView from '../views/CheckDetailView.vue'
import DashboardView from '../views/DashboardView.vue'
import GroupDetailView from '../views/GroupDetailView.vue'
import PublicStatusView from '../views/PublicStatusView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/groups/:id', name: 'group-detail', component: GroupDetailView, props: true },
    { path: '/checks/:id', name: 'check-detail', component: CheckDetailView, props: true },
    { path: '/status', name: 'public-status', component: PublicStatusView },
  ],
})
