import { defineWorkersProject } from '@cloudflare/vitest-pool-workers/config'
import tsconfigPaths from 'vite-tsconfig-paths'

import { dispatchHandlers } from './tests/workers/fixtures/handlers'

// vitest-pool-workers runs tests inside the real workerd runtime. Workerd's
// fetch can't be patched from the test process, so MSW's setupServer-style
// global interception doesn't apply here. Miniflare's `outboundService` is
// invoked from this Node config whenever the worker makes an outbound HTTP
// call — that's the workerd-equivalent escape hatch. We hand each request to
// MSW's `RequestHandler#run()` so handlers declared with the standard
// `http.*` DSL (see tests/workers/fixtures/handlers.ts) match and respond.
// Fixtures are real PostHog API responses captured from a local dev server.

export default defineWorkersProject({
    plugins: [tsconfigPaths({ root: '.' })],
    test: {
        name: 'workers',
        include: ['tests/workers/**/*.test.ts'],
        // The first test in each file pays workerd + DurableObject cold-start
        // overhead that can push it past the 5s default. Bump the ceiling so
        // these tests don't flake on slower CI runners.
        testTimeout: 15000,
        poolOptions: {
            workers: {
                singleWorker: true,
                wrangler: { configPath: './wrangler.jsonc' },
                miniflare: {
                    bindings: {
                        // Override secrets loaded from .dev.vars. Empty values
                        // make init()'s analytics / observability paths short-
                        // circuit cleanly.
                        POSTHOG_API_BASE_URL: '',
                        POSTHOG_ANALYTICS_API_KEY: '',
                        POSTHOG_ANALYTICS_HOST: '',
                        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: '',
                        POSTHOG_UI_APPS_TOKEN: '',
                        MCP_CAT_PROJECT_ID: '',
                        // Generic test marker. Code can short-circuit features
                        // that need real network (e.g. context-mill GitHub
                        // fetch in src/resources/index.ts).
                        TEST: '1',
                    },
                    outboundService: dispatchHandlers,
                },
            },
        },
    },
})
