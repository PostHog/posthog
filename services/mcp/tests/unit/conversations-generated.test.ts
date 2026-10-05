import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/conversations'
import type { Context } from '@/tools/types'

describe('Generated conversations tools', () => {
    it('conversations-tickets-retrieve returns a compact person summary without replay or enrichment data', async () => {
        const ticket = {
            id: '00000000-0000-4000-8000-000000000001',
            ticket_number: 7,
            status: 'open',
            distinct_id: 'user-1',
            session_id: 'session-1',
            session_context: {
                current_url: 'https://example.com/billing',
                replay_url: 'https://example.com/replay/session-1',
                browser: 'Chrome',
            },
            person: {
                id: '00000000-0000-4000-8000-000000000002',
                name: 'Test Person',
                is_identified: true,
                distinct_ids: ['user-1', 'anon-1'],
                properties: { email: 'person@example.com', $geoip_city_name: 'Testville' },
                created_at: '2026-01-01T00:00:00Z',
            },
        }
        const context = {
            api: {
                request: vi.fn().mockResolvedValue(ticket),
                getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
            },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS['conversations-tickets-retrieve']!()

        const result = (await tool.handler(context, tool.schema.parse({ id: ticket.id }))) as Record<string, unknown>

        expect(result.person).toEqual({
            id: '00000000-0000-4000-8000-000000000002',
            name: 'Test Person',
            is_identified: true,
        })
        expect(result.session_context).toEqual({ current_url: 'https://example.com/billing' })
        expect(result.session_id).toBe('session-1')
        expect(result.distinct_id).toBe('user-1')
    })
})
