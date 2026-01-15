import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' })],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        retry: 1, // Retry failed tests once to handle flaky integration tests
        setupFiles: ['tests/setup.ts'],
        include: ['tests/**/*.integration.test.ts'],
        exclude: ['node_modules/**', 'dist/**'],
        // Run test files sequentially to reduce parallel API load
        fileParallelism: false,
        // Limit concurrent tests within a file
        maxConcurrency: 5,
    },
})
