import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        // No built-in retry: ci-mcp.yml reruns failed files into a second JUnit report, so the
        // first report keeps the raw flake signal for Trunk. A vitest retry would record a
        // flaky test as a plain pass and hide it from that report.
        retry: 0,
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
