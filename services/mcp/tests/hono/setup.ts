import { vi } from 'vitest'

vi.mock('cloudflare:workers', () => ({
    env: {
        INKEEP_API_KEY: undefined,
        POSTHOG_API_BASE_URL: undefined,
        MCP_APPS_BASE_URL: undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
        POSTHOG_UI_APPS_TOKEN: undefined,
        POSTHOG_ANALYTICS_API_KEY: undefined,
        POSTHOG_ANALYTICS_HOST: undefined,
        MCP_CAT_PROJECT_ID: undefined,
    },
}))

vi.mock('@/resources/ui-apps', () => ({
    registerUiAppResources: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/resources/ui-apps.generated', () => ({
    UI_APP_REGISTRY: {},
}))

vi.mock('mcpcat', () => ({
    track: vi.fn(),
}))
