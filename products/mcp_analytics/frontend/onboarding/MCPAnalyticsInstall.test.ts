import type { LiveEvent } from '~/types'

import { liveEventRows } from './MCPAnalyticsInstall'

describe('liveEventRows', () => {
    it('shows only MCP events without exposing their properties', () => {
        const mcpEvent = {
            uuid: 'mcp-event',
            event: '$mcp_tool_call',
            properties: { api_key: 'secret-value' },
            timestamp: '2026-07-28T12:00:00Z',
            created_at: '2026-07-28T12:00:01Z',
            team_id: 1,
            distinct_id: 'person-1',
        } satisfies LiveEvent
        const unrelatedEvent = {
            ...mcpEvent,
            uuid: 'pageview-event',
            event: '$pageview',
        }

        expect(liveEventRows([unrelatedEvent, mcpEvent])).toEqual([
            {
                uuid: 'mcp-event',
                event: '$mcp_tool_call',
                receivedAt: '12:00:01',
            },
        ])
    })
})
