import type { LiveEvent } from '~/types'

import { liveEventRows } from './MCPAnalyticsInstall'

describe('liveEventRows', () => {
    it('builds rows from incoming events without exposing their properties', () => {
        const event = {
            uuid: 'event-1',
            event: 'unexpected_mcp_event',
            properties: { api_key: 'secret-value' },
            timestamp: '2026-07-28T12:00:00Z',
            created_at: '2026-07-28T12:00:01Z',
            team_id: 1,
            distinct_id: 'person-1',
        } satisfies LiveEvent

        expect(liveEventRows([event])).toEqual([
            {
                uuid: 'event-1',
                event: 'unexpected_mcp_event',
                receivedAt: '12:00:01',
            },
        ])
    })
})
