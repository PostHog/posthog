import { SessionManager } from '@/lib/utils/SessionManager'
import { getToolsFromContext } from '@/tools'
import { getToolsForFeatures } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'
import { describe, expect, it } from 'vitest'

describe('Tool Filtering - Features', () => {
    const featureTests = [
        {
            features: undefined,
            description: 'all tools when no features specified',
            expectedTools: [
                'feature-flag-get-definition',
                'dashboard-create',
                'insights-get-all',
                'organizations-get',
            ],
        },
        {
            features: [],
            description: 'all tools when empty array passed',
            expectedTools: ['feature-flag-get-definition', 'dashboard-create'],
        },
        {
            features: ['flags'],
            description: 'flag tools only',
            expectedTools: [
                'feature-flag-get-definition',
                'feature-flag-get-all',
                'create-feature-flag',
                'update-feature-flag',
                'delete-feature-flag',
            ],
        },
        {
            features: ['dashboards', 'insights'],
            description: 'dashboard and insight tools',
            expectedTools: [
                'dashboard-create',
                'dashboards-get-all',
                'add-insight-to-dashboard',
                'insights-get-all',
                'query-generate-hogql-from-question',
                'query-run',
                'insight-create-from-query',
            ],
        },
        {
            features: ['workspace'],
            description: 'workspace tools',
            expectedTools: [
                'organizations-get',
                'switch-organization',
                'projects-get',
                'switch-project',
                'property-definitions',
            ],
        },
        {
            features: ['error-tracking'],
            description: 'error tracking tools',
            expectedTools: ['list-errors', 'error-details'],
        },
        {
            features: ['experiments'],
            description: 'experiment tools',
            expectedTools: ['experiment-get-all'],
        },
        {
            features: ['llm-analytics'],
            description: 'LLM analytics tools',
            expectedTools: ['get-llm-total-costs-for-project'],
        },
        {
            features: ['docs'],
            description: 'documentation tools',
            expectedTools: ['docs-search'],
        },
        {
            features: ['invalid', 'flags'],
            description: 'valid tools when mixed with invalid features',
            expectedTools: ['feature-flag-get-definition'],
        },
        {
            features: ['invalid', 'unknown'],
            description: 'empty array for only invalid features',
            expectedTools: [],
        },
    ]

    describe('getToolsForFeatures', () => {
        it.each(featureTests)('should return $description', ({ features, expectedTools }) => {
            const tools = getToolsForFeatures(features)

            for (const tool of expectedTools) {
                expect(tools).toContain(tool)
            }
        })
    })
})

const createMockContext = (scopes: string[]): Context => ({
    api: {} as any,
    cache: {} as any,
    env: { INKEEP_API_KEY: undefined },
    stateManager: {
        getApiKey: async () => ({ scopes }),
    } as any,
    sessionManager: new SessionManager({} as any),
})

describe('Tool Filtering - API Scopes', () => {
    it('should return all tools when user has * scope', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-create')
        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('insight-create-from-query')
        expect(toolNames.length).toBeGreaterThan(25)
    })

    it('should only return dashboard tools when user has dashboard scopes', async () => {
        const context = createMockContext(['dashboard:read', 'dashboard:write'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-create')
        expect(toolNames).toContain('dashboard-get')
        expect(toolNames).toContain('dashboards-get-all')
        expect(toolNames).toContain('add-insight-to-dashboard')

        expect(toolNames).not.toContain('create-feature-flag')
        expect(toolNames).not.toContain('organizations-get')
    })

    it('should include read tools when user has write scope', async () => {
        const context = createMockContext(['feature_flag:write'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('feature-flag-get-all')
        expect(toolNames).toContain('feature-flag-get-definition')

        expect(toolNames).not.toContain('dashboard-create')
    })

    it('should only return read tools when user has read scope', async () => {
        const context = createMockContext(['insight:read'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('insights-get-all')
        expect(toolNames).toContain('insight-get')

        expect(toolNames).not.toContain('insight-create-from-query')
        expect(toolNames).not.toContain('dashboard-create')
    })

    it('should return multiple scope tools when user has multiple scopes', async () => {
        const context = createMockContext([
            'dashboard:read',
            'feature_flag:write',
            'organization:read',
        ])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-get')
        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('organization-details-get')

        expect(toolNames).not.toContain('dashboard-create')
        expect(toolNames).not.toContain('insight-create-from-query')
    })

    it('should return empty array when user has no matching scopes', async () => {
        const context = createMockContext(['some:unknown'])
        const tools = await getToolsFromContext(context)

        expect(tools).toHaveLength(0)
    })

    it('should return empty array when user has empty scopes', async () => {
        const context = createMockContext([])
        const tools = await getToolsFromContext(context)

        expect(tools).toHaveLength(0)
    })
})
