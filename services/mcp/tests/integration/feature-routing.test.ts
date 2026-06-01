import { describe, expect, it } from 'vitest'

import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'

const createMockContext = (): Context => ({
    api: {} as any,
    cache: {} as any,
    env: {
        MCP_APPS_BASE_URL: undefined,
        POSTHOG_ANALYTICS_API_KEY: undefined,
        POSTHOG_ANALYTICS_HOST: undefined,
        POSTHOG_API_BASE_URL: undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
        POSTHOG_UI_APPS_TOKEN: undefined,
    },
    stateManager: {
        getApiKey: async () => ({ scopes: ['*'] }),
        getAiConsentGiven: async () => undefined,
    } as any,
    sessionManager: new SessionManager({} as any),
    getDistinctId: async () => 'test-distinct-id',
    trackEvent: async () => {},
})

describe('Feature Routing Integration', () => {
    const integrationTests = [
        {
            features: undefined,
            description: 'all tools when no features specified',
            expectedTools: [
                'feature-flag-get-definition',
                'dashboard-create',
                'insights-list',
                'organizations-list',
                'query-error-tracking-issues',
            ],
        },
        {
            features: ['dashboards'],
            description: 'only dashboard tools',
            expectedTools: [
                'dashboard-create',
                'dashboards-get-all',
                'dashboard-get',
                'dashboard-update',
                'dashboard-delete',
                'dashboard-reorder-tiles',
            ],
        },
        {
            features: ['flags', 'workspace'],
            description: 'tools from multiple features',
            expectedTools: [
                'feature-flag-get-definition',
                'create-feature-flag',
                'feature-flag-get-all',
                'switch-organization',
                'projects-get',
            ],
        },
        {
            features: ['invalid', 'flags', 'unknown'],
            description: 'valid tools ignoring invalid features',
            expectedTools: ['feature-flag-get-definition', 'create-feature-flag'],
        },
    ]

    it.each(integrationTests)('should return $description', async ({ features, expectedTools }) => {
        const context = createMockContext()
        const tools = await getToolsFromContext(context, { features })
        const toolNames = tools.map((t) => t.name)

        for (const tool of expectedTools) {
            expect(toolNames).toContain(tool)
        }
    })
})
