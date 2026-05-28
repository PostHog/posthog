import { defineConfig } from 'vitest/config'

export default defineConfig({
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 30_000,
        globals: true,
        fileParallelism: false,
    },
})
