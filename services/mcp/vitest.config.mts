import { resolve } from 'path'
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
        // Materializes `shared/guidelines.md` (imported via the `@shared/*` alias by the
        // dispatcher and the unit suite) before any project runs — see tests/global-setup.ts.
        globalSetup: ['tests/global-setup.ts'],
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
                        'tests/hono/**',
                    ],
                },
            },
            {
                plugins: [tsconfigPaths({ root: '.' }), markdownLoader],
                resolve: {
                    // Mirrors the alias setup in vite.ui-apps.config.ts so the visualizer import
                    // chain (which reaches outside this package via the `products` alias) resolves.
                    // `@posthog/quill` points at source rather than dist so tests don't require a
                    // prior `pnpm build:quill`.
                    alias: [
                        // Files reached via the `products` alias resolve bare imports from their
                        // own directory, which has no node_modules — pin react to this package's copy.
                        { find: 'react', replacement: resolve(__dirname, 'node_modules/react') },
                        { find: 'react-dom', replacement: resolve(__dirname, 'node_modules/react-dom') },
                        { find: 'products', replacement: resolve(__dirname, '../../products') },
                        { find: '@posthog/mcp-ui', replacement: resolve(__dirname, 'src/ui-apps/lib') },
                        {
                            find: /^@posthog\/quill$/,
                            replacement: resolve(__dirname, '../../packages/quill/packages/quill/src/index.ts'),
                        },
                        {
                            find: /^@posthog\/quill-charts$/,
                            replacement: resolve(__dirname, '../../packages/quill/packages/charts/src/index.ts'),
                        },
                        { find: /^lucide-react$/, replacement: resolve(__dirname, 'node_modules/lucide-react') },
                        { find: '@common', replacement: resolve(__dirname, '../../common') },
                    ],
                },
                test: {
                    name: 'ui-apps-render',
                    globals: true,
                    environment: 'node',
                    testTimeout: 10000,
                    setupFiles: ['tests/render/setup.ts'],
                    include: ['tests/render/**/*.test.tsx'],
                },
            },
            './vitest.workers.config.mts',
        ],
    },
})
