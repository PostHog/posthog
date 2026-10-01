import { describe, expect, it, vi } from 'vitest'

import { getToolsFromContext } from '@/tools'
import { GENERATED_TOOLS } from '@/tools/generated/core'
import type { Context } from '@/tools/types'

function createMockContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request },
        cache: {},
        stateManager: { getOrgID: async () => 'org-abc' },
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

function createScopedContext(scopes: string[]): Context {
    return {
        stateManager: {
            getApiKey: async () => ({ scopes }),
            getAiConsentGiven: async () => true,
        },
    } as unknown as Context
}

describe('project-create', () => {
    const tool = GENERATED_TOOLS['project-create']!()

    it('posts to the active organization and sends only the project name', async () => {
        const request = vi.fn().mockResolvedValue({ id: 7, name: 'Staging' })

        await tool.handler(createMockContext(request), { name: 'Staging' })

        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/organizations/org-abc/projects/',
            body: { name: 'Staging' },
        })
    })

    it('returns the new project ID and API token but never the secret tokens', async () => {
        // The create response carries the full project serializer, so the raw data
        // includes server-side secrets that must not reach the model.
        const request = vi.fn().mockResolvedValue({
            id: 7,
            name: 'Staging',
            organization: 'org-abc',
            api_token: 'phc_public',
            created_at: '2026-09-19T00:00:00Z',
            secret_api_token: 'phs_secret',
            secret_api_token_backup: 'phs_secret_backup',
            live_events_token: 'live_secret',
        })

        const result = await tool.handler(createMockContext(request), {
            name: 'Staging',
        })

        expect(result).toEqual({
            id: 7,
            name: 'Staging',
            organization: 'org-abc',
            api_token: 'phc_public',
            created_at: '2026-09-19T00:00:00Z',
        })
    })

    it.each([
        ['project:write', true],
        ['project:read', false],
    ])('is offered to a %s key: %s', async (scope, offered) => {
        const tools = await getToolsFromContext(createScopedContext([scope]))

        expect(tools.map((tool) => tool.name).includes('project-create')).toBe(offered)
    })
})
