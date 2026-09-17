import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/conversations'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// A ticket whose person carries the property dict a real person accumulates. Only the identity
// fields may survive projection — the properties are what crowd the ticket content out.
const TICKET = {
    id: 'a0000000-0000-4000-8000-000000000001',
    ticket_number: 41,
    status: 'open',
    last_message_text: 'The export never finished.',
    person: {
        id: 'b0000000-0000-4000-8000-000000000002',
        name: 'reporter@example.com',
        distinct_ids: ['distinct-1'],
        is_identified: true,
        created_at: '2026-07-13T00:00:00Z',
        properties: {
            email: 'reporter@example.com',
            $initial_referring_domain: 'example.com',
            $geoip_city_name: 'Nowhere',
            plan: 'scale',
        },
    },
    identity_verified: true,
}

function mockContext(response: unknown): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => response,
        },
    } as unknown as Context
}

describe('support ticket reads', () => {
    it('returns the reporter identity without the person property dict', async () => {
        const tool = GENERATED_TOOLS['conversations-tickets-retrieve'] as () => ToolBase<ZodObjectAny>
        const result: any = await tool().handler(mockContext(TICKET), { id: TICKET.id })

        expect(result.person).toEqual({
            id: TICKET.person.id,
            name: TICKET.person.name,
            distinct_ids: TICKET.person.distinct_ids,
            is_identified: true,
            created_at: TICKET.person.created_at,
        })
        expect(result.last_message_text).toBe('The export never finished.')
    })

    it('reports the next page of a message thread as an offset, not a link', async () => {
        const tool = GENERATED_TOOLS['conversations-tickets-messages-retrieve'] as () => ToolBase<ZodObjectAny>
        const result: any = await tool().handler(
            mockContext({
                count: 120,
                next: 'http://posthog-api.internal:8000/api/projects/1/conversations/tickets/1/messages/?limit=50&offset=50',
                previous: null,
                results: [{ id: 'm1', author_type: 'customer', content: 'The export never finished.' }],
            }),
            { id: TICKET.id }
        )

        expect(result).not.toHaveProperty('next')
        expect(result).not.toHaveProperty('previous')
        expect(result.next_offset).toBe(50)
        expect(result.previous_offset).toBeNull()
    })
})
