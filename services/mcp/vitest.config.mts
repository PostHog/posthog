import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// Markdown loader so *.md imports resolve as string exports.
const markdownLoader = {
    name: 'markdown-loader',
    transform(code: string, id: string) {
        if (id.endsWith('.md')) {
            return {
                code: `export default ${JSON.stringify(code)}`,
                map: null,
            }
        }
    },
}

// Default `pnpm test` runs the fast Node-pool unit suite. Hono protocol tests
// live in `vitest.hono.config.mts`; integration tests that need a real PostHog
// backend live in `vitest.integration.config.mts`.
export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), markdownLoader],
    test: {
        name: 'unit',
        globals: true,
        environment: 'node',
        testTimeout: 10000,
        setupFiles: ['tests/setup.ts'],
        include: ['tests/**/*.test.ts'],
        exclude: ['node_modules/**', 'dist/**', 'tests/**/*.integration.test.ts', 'tests/hono/**'],
    },
})
