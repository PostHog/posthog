import { defineConfig } from 'vitest/config'

export default defineConfig({
    test: {
        globals: true,
        environment: 'node',
        include: ['tests/e2e/**/*.e2e.test.ts'],
        testTimeout: 30000,
        hookTimeout: 20000,
        sequence: { concurrent: false },
    },
})
