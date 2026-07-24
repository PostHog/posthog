import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 120000,
        setupFiles: ['tests/hono/setup.ts'],
        include: ['tests/hono/**/*.perf.ts'],
    },
})
