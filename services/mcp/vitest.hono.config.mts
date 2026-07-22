import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 15000,
        setupFiles: ['tests/hono/setup.ts'],
        include: ['tests/hono/**/*.test.ts'],
        exclude: ['node_modules/**', 'dist/**', 'tests/hono/**/*.integration.test.ts'],
    },
})
