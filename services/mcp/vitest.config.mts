import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// Shared markdown loader so *.md imports resolve as string exports in the
// Node-pool project. The workers-pool project has its own transform stack.
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

// Two projects run under a single `pnpm test` invocation:
//   - `unit`    → fast Node-pool suite (default pool, ~2s)
//   - `workers` → DO/runtime integration via @cloudflare/vitest-pool-workers
// Integration tests that need a real PostHog backend stay in their own
// config (vitest.integration.config.mts) — they boot the full stack and
// aren't suitable for the default run.
export default defineConfig({
    test: {
        projects: [
            {
                plugins: [tsconfigPaths({ root: '.' }), markdownLoader],
                test: {
                    name: 'unit',
                    globals: true,
                    environment: 'node',
                    testTimeout: 10000,
                    setupFiles: ['tests/setup.ts'],
                    include: ['tests/**/*.test.ts'],
                    exclude: [
                        'node_modules/**',
                        'dist/**',
                        'tests/**/*.integration.test.ts',
                        'tests/workers/**',
                    ],
                },
            },
            './vitest.workers.config.mts',
        ],
    },
})
