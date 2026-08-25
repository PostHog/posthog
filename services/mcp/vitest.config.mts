import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

import { textLoader } from './tests/vitest-text-loader'

// Two projects run under a single `pnpm test` invocation:
//   - `unit`    → fast Node-pool suite (default pool, ~2s)
//   - `workers` → edge-proxy worker entry-point HTTP behavior via
//                 @cloudflare/vitest-pool-workers
// Integration tests that need a real PostHog backend stay in their own
// config (vitest.integration.config.mts) — they boot the full stack and
// aren't suitable for the default run.
export default defineConfig({
    test: {
        // Materializes `shared/guidelines.md` (imported via the `@shared/*` alias by the
        // dispatcher and the unit suite) before any project runs — see tests/global-setup.ts.
        globalSetup: ['tests/global-setup.ts'],
        projects: [
            {
                plugins: [tsconfigPaths({ root: '.' }), textLoader],
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
                        'tests/hono/**',
                    ],
                },
            },
            './vitest.workers.config.mts',
        ],
    },
})
