import { defineConfig } from 'vitest/config'

export default defineConfig({
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 10_000,
        globals: true,
    },
})
