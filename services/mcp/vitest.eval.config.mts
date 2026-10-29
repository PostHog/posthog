import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

// Evals call a real model, so they never run with the default or CI test configs.
export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 60 * 60 * 1000,
        setupFiles: ['tests/hono/setup.ts'],
        include: ['tests/evals/**/*.eval.ts'],
    },
})
