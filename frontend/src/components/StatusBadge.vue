<script setup lang="ts">
defineProps<{ status: 'up' | 'down' | 'paused' }>()
</script>

<template>
  <span class="badge" :class="status">
    <template v-if="status === 'up'">● работает</template>
    <template v-else-if="status === 'down'">● упал</template>
    <template v-else>⏸ на паузе</template>
  </span>
</template>
