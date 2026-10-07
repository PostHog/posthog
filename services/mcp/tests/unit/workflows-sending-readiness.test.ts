import { describe, expect, it, vi } from 'vitest'

import { getToolsFromContext } from '@/tools'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

function createContext(scopes: string[] = ['hog_flow:read']): {
    context: Context
    request: ReturnType<typeof vi.fn>
} {
    const request = vi.fn()
    const context = {
        api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
        stateManager: {
            getApiKey: async () => ({ scopes }),
            getAiConsentGiven: async () => true,
            getProjectId: async () => '42',
        },
    } as unknown as Context
    return { context, request }
}

async function getTool(context: Context, name: string): Promise<Tool<ZodObjectAny>> {
    const tools = await getToolsFromContext(context, { featureFlags: { 'workflows-email-domain-agent-setup': true } })
    const tool = tools.find((candidate) => candidate.name === name)
    expect(tool, `${name} should be available`).not.toBeUndefined()
    return tool!
}

describe('workflow email sending readiness', () => {
    it.each([
        { scopes: ['hog_flow:read'], enabled: true, visible: true },
        { scopes: ['hog_flow:write'], enabled: true, visible: true },
        { scopes: [], enabled: true, visible: false },
        { scopes: ['integration:read'], enabled: true, visible: false },
        { scopes: ['hog_flow:read'], enabled: false, visible: false },
        { scopes: ['hog_flow:read'], enabled: undefined, visible: false },
    ])('requires workflow access and stays read-only: %j', async ({ scopes, enabled, visible }) => {
        const { context, request } = createContext(scopes)
        const tools = await getToolsFromContext(context, {
            readOnly: true,
            featureFlags: { 'workflows-email-domain-agent-setup': enabled },
        })
        const names = tools.map((tool) => tool.name)
        expect(names.includes('workflows-email-sending-suspension')).toBe(visible)
        expect(names.includes('workflows-email-reputation')).toBe(visible)
        if (scopes.some((scope) => scope.startsWith('hog_flow:'))) {
            expect(names).toContain('workflows-get')
        }
        expect(names).not.toContain('hog-flows-resume-email-sending')
        expect(request).not.toHaveBeenCalled()
    })

    it('reads project suspension with workflow read access', async () => {
        const { context, request } = createContext()
        const suspension = {
            email_sending_suspended: true,
            email_sending_suspended_at: '2026-01-01T00:00:00Z',
            email_sending_suspension_reason: 'Sending suspended',
        }
        request.mockResolvedValue(suspension)

        const tool = await getTool(context, 'workflows-email-sending-suspension')
        expect(tool.scopes).toEqual(['hog_flow:read'])
        expect(tool.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false })
        expect(await tool.handler(context, tool.schema.parse({}))).toEqual(suspension)
        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'GET',
            path: '/api/projects/42/hog_flows/email_sending_suspension/',
        })
    })

    it('preserves withheld project aggregates and a visible paused workflow', async () => {
        const { context, request } = createContext()
        const reputation = {
            aws: null,
            reputation: null,
            sending_allowance: null,
            workflows: [
                {
                    hog_flow_id: '00000000-0000-4000-8000-000000000001',
                    email_sending_paused: true,
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason: 'High bounce rate',
                },
            ],
            isps: [],
            isp_withheld_domains: ['example.com'],
            isp_shared_domains: [],
            email_sending_suspended: false,
            email_sending_suspended_at: null,
            email_sending_suspension_reason: '',
        }
        request.mockResolvedValue(reputation)

        const tool = await getTool(context, 'workflows-email-reputation')
        expect(tool.scopes).toEqual(['hog_flow:read'])
        expect(tool.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false })
        expect(await tool.handler(context, tool.schema.parse({ search: 'Welcome' }))).toEqual(reputation)
        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'GET',
            path: '/api/projects/42/hog_flows/reputation/',
            query: { search: 'Welcome' },
        })
    })

    it.each([true, false, undefined])('reads sender verification without other config: %s', async (verified) => {
        const { context, request } = createContext(['integration:read'])
        request.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: 7,
                    kind: 'email',
                    display_name: 'sender@example.com',
                    errors: '',
                    config: { ...(verified === undefined ? {} : { verified }), secret: 'synthetic-test-secret' },
                },
            ],
        })

        const tool = await getTool(context, 'integrations-list')
        const result = await tool.handler(context, tool.schema.parse({ kind: 'email' }))
        expect(result).toEqual({
            count: 1,
            next: null,
            previous: null,
            _posthogUrl: 'https://example.com/project/42/settings/environment-integrations',
            results: [
                {
                    id: 7,
                    kind: 'email',
                    display_name: 'sender@example.com',
                    errors: '',
                    config: verified === undefined ? {} : { verified },
                },
            ],
        })
        expect(JSON.stringify(result)).not.toContain('synthetic-test-secret')
        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'GET',
            path: '/api/projects/42/integrations/',
            query: { kind: 'email', limit: undefined, offset: undefined },
        })
    })

    it('returns no visible sender without inventing verification', async () => {
        const { context, request } = createContext(['integration:read'])
        request.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        const tool = await getTool(context, 'integrations-list')
        expect(await tool.handler(context, tool.schema.parse({ kind: 'email' }))).toMatchObject({
            count: 0,
            next: null,
            results: [],
        })
    })

    it('reads pause state for a workflow absent from reputation rows', async () => {
        const { context, request } = createContext()
        const id = '00000000-0000-4000-8000-000000000001'
        const workflow = {
            id,
            name: 'Welcome',
            status: 'active',
            email_sending_paused_at: '2026-01-01T00:00:00Z',
            email_sending_paused_reason: 'High bounce rate',
        }
        request.mockResolvedValue(workflow)
        const tool = await getTool(context, 'workflows-get')
        expect(await tool.handler(context, tool.schema.parse({ id }))).toMatchObject(workflow)
        expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'GET', path: `/api/projects/42/hog_flows/${id}/` })
    })

    it.each(['workflows-email-sending-suspension', 'workflows-email-reputation'])(
        'propagates denied and unavailable reads for %s',
        async (name) => {
            const { context, request } = createContext()
            const tool = await getTool(context, name)
            for (const error of [new Error('403 Forbidden'), new Error('503 Service unavailable')]) {
                request.mockRejectedValueOnce(error)
                await expect(tool.handler(context, tool.schema.parse({}))).rejects.toBe(error)
            }
            expect(request).toHaveBeenCalledTimes(2)
        }
    )

    it('preserves absent reputation data without adding defaults', async () => {
        const { context, request } = createContext()
        request.mockResolvedValue({ workflows: [] })
        const tool = await getTool(context, 'workflows-email-reputation')
        expect(await tool.handler(context, tool.schema.parse({}))).toEqual({ workflows: [] })
    })

    it('supports explicitly unavailable readiness tools', async () => {
        const { context, request } = createContext()
        const names = (
            await getToolsFromContext(context, {
                featureFlags: { 'workflows-email-domain-agent-setup': true },
                excludeTools: ['workflows-email-sending-suspension', 'workflows-email-reputation'],
            })
        ).map((tool) => tool.name)
        expect(names).not.toContain('workflows-email-sending-suspension')
        expect(names).not.toContain('workflows-email-reputation')
        expect(request).not.toHaveBeenCalled()
    })
})
