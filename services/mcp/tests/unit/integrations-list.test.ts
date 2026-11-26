import { describe, expect, it, vi } from 'vitest'

import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'

describe('integrations-list', () => {
    it.each([true, false, undefined])('reads sender verification without other config: %s', async (verified) => {
        const request = vi.fn().mockResolvedValue({
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
        const context = {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
            stateManager: {
                getApiKey: async () => ({ scopes: ['integration:read'] }),
                getAiConsentGiven: async () => true,
                getProjectId: async () => '42',
            },
        } as unknown as Context

        const tools = await getToolsFromContext(context)
        const tool = tools.find((candidate) => candidate.name === 'integrations-list')
        expect(tool, 'integrations-list should be available').not.toBeUndefined()
        const result = await tool!.handler(context, tool!.schema.parse({ kind: 'email' }))

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
})
