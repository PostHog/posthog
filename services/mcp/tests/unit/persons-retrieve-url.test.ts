import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/persons'
import type { Context } from '@/tools/types'

describe('persons-retrieve', () => {
    // The person scene routes by UUID (urls.personByUUID); a numeric-id link
    // renders "we couldn't load this person".
    it('links _posthogUrl to the person page by uuid, not numeric id', async () => {
        const person = {
            id: 447933,
            uuid: '0192aa67-2c4c-0000-fcc6-7798e4d175e0',
            name: 'Test person',
            properties: {},
            distinct_ids: ['d1'],
            created_at: '2026-01-01T00:00:00Z',
            last_seen_at: null,
        }
        const request = vi.fn().mockResolvedValue(person)
        const context = {
            api: { request, getProjectBaseUrl: () => 'https://us.posthog.com/project/42' },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context

        const tool = GENERATED_TOOLS['persons-retrieve']!()
        const result = (await tool.handler(context, tool.schema.parse({ id: '447933' }))) as {
            _posthogUrl: string
        }

        expect(result._posthogUrl).toBe(
            'https://us.posthog.com/project/42/persons/0192aa67-2c4c-0000-fcc6-7798e4d175e0'
        )
    })
})
