import { defineWorkersProject } from '@cloudflare/vitest-pool-workers/config'
import tsconfigPaths from 'vite-tsconfig-paths'

// Cold-start `MCP.init()` fires several outbound calls that would otherwise hit
// the real PostHog API. We want init() to complete without hanging so the DO
// reaches the "started" state — warm-DO `setName()` only short-circuits once
// status is "started". The strategy: stub oauth/introspect with a valid
// payload so `StateManager.getApiKey()` returns, and let every other call 404
// (all are wrapped in try/catch inside init()).
const INTROSPECT_OK_BODY = JSON.stringify({
    active: true,
    scope: '',
    scoped_teams: [],
    scoped_organizations: [],
})

export default defineWorkersProject({
    plugins: [tsconfigPaths({ root: '.' })],
    test: {
        name: 'workers',
        include: ['tests/workers/**/*.test.ts'],
        poolOptions: {
            workers: {
                singleWorker: true,
                wrangler: { configPath: './wrangler.jsonc' },
                miniflare: {
                    // Override secrets loaded from .dev.vars. Leaving PostHog
                    // analytics / observability secrets unset makes init() skip
                    // code paths that would otherwise call users/@me during
                    // mcpcat setup (which throws on 404 and aborts init).
                    bindings: {
                        POSTHOG_API_BASE_URL: '',
                        POSTHOG_ANALYTICS_API_KEY: '',
                        POSTHOG_ANALYTICS_HOST: '',
                        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: '',
                        POSTHOG_UI_APPS_TOKEN: '',
                        INKEEP_API_KEY: '',
                        MCP_CAT_PROJECT_ID: '',
                    },
                    outboundService: (request) => {
                        const url = new URL(request.url)
                        if (url.pathname.includes('/oauth/introspect')) {
                            return new Response(INTROSPECT_OK_BODY, {
                                status: 200,
                                headers: { 'content-type': 'application/json' },
                            })
                        }
                        return new Response(null, { status: 404 })
                    },
                },
            },
        },
    },
})
