import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        retry: 1, // Retry failed tests once to handle flaky integration tests
        setupFiles: ['tests/setup.ts'],
        // Builds `public/ui-apps/*` once per test session if missing — required for
        // the MCP-protocol integration tests that exercise UI app resources.
        globalSetup: ['tests/integration/global-setup.ts'],
        include: ['tests/**/*.integration.test.ts'],
        exclude: ['node_modules/**', 'dist/**', 'tests/hono/**'],
        // Run test files sequentially to reduce parallel API load
        fileParallelism: false,
        // Limit concurrent tests within a file
        maxConcurrency: 5,
    },
})
