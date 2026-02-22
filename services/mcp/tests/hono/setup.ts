import { vi } from 'vitest'

vi.mock('cloudflare:workers', () => ({
    env: {
        INKEEP_API_KEY: undefined,
        POSTHOG_API_BASE_URL: undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
        POSTHOG_UI_APPS_TOKEN: undefined,
    },
}))

vi.mock('@/resources/ui-apps', () => ({
    registerUiAppResources: vi.fn().mockResolvedValue(undefined),
    QUERY_RESULTS_RESOURCE_URI: 'posthog://ui-apps/query-results',
    DEMO_RESOURCE_URI: 'posthog://ui-apps/demo',
}))
