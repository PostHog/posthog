import { render, screen } from '@testing-library/react'

import type { LiveEvent } from '~/types'

import { MCPAnalyticsLiveEvents } from './MCPAnalyticsInstall'

describe('MCPAnalyticsLiveEvents', () => {
    it('shows incoming event names without exposing their properties', () => {
        const event = {
            uuid: 'event-1',
            event: 'unexpected_mcp_event',
            properties: { api_key: 'secret-value' },
            timestamp: '2026-07-28T12:00:00Z',
            created_at: '2026-07-28T12:00:01Z',
            team_id: 1,
            distinct_id: 'person-1',
        } satisfies LiveEvent

        render(<MCPAnalyticsLiveEvents events={[event]} />)

        expect(screen.getByText('unexpected_mcp_event')).toBeTruthy()
        expect(screen.queryByText('secret-value')).toBeNull()
    })
})
