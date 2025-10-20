import { SessionManager } from '@/lib/utils/SessionManager'
import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'
import { describe, expect, it } from 'vitest'

const createMockContext = (): Context => ({
    api: {} as any,
    cache: {} as any,
    env: { INKEEP_API_KEY: undefined },
    stateManager: {
        getApiKey: async () => ({ scopes: ['*'] }),
    } as any,
    sessionManager: new SessionManager({} as any),
})

describe('Feature Routing Integration', () => {
    const integrationTests = [
        {
            features: undefined,
            description: 'all tools when no features specified',
            expectedTools: [
                'feature-flag-get-definition',
                'dashboard-create',
                'insights-get-all',
                'organizations-get',
                'list-errors',
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
                'add-insight-to-dashboard',
            ],
        },
        {
            features: ['flags', 'workspace'],
            description: 'tools from multiple features',
            expectedTools: [
                'feature-flag-get-definition',
                'create-feature-flag',
                'feature-flag-get-all',
                'organizations-get',
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
        const tools = await getToolsFromContext(context, features)
        const toolNames = tools.map((t) => t.name)

        for (const tool of expectedTools) {
            expect(toolNames).toContain(tool)
        }
    })
})
