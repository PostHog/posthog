import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { sessionsUrl } from './NotableSessionsTable'

describe('sessionsUrl', () => {
    const toolFilter: AnyPropertyFilter = {
        key: '$mcp_tool_name',
        value: ['create_insight'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }
    const sessionFilter = (sessionId: string): AnyPropertyFilter => ({
        key: '$session_id',
        value: [sessionId],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    })
    const sharedParams = {
        date_from: '-7d',
        has_errors: 'true',
        properties: [toolFilter, sessionFilter('old-session')],
    }

    it('links a notable session through the shared property filters', () => {
        expect(sessionsUrl({ ...sharedParams, search: 'old-session' }, 'linked-session')).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), {
                ...sharedParams,
                properties: [toolFilter, sessionFilter('linked-session')],
            }).url
        )
    })

    it('opens the full session list without stale session filters', () => {
        expect(sessionsUrl({ ...sharedParams, search: 'old-session' })).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), { ...sharedParams, properties: [toolFilter] }).url
        )
    })
})
