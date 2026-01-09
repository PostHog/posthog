import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' })],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        retry: process.env.CI ? 1 : 0, // Retry failed tests once in CI to handle flaky integration tests
        setupFiles: ['tests/setup.ts'],
        include: ['tests/**/*.integration.test.ts'],
        exclude: ['node_modules/**', 'dist/**'],
    },
})
