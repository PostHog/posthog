import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpSessionUrl, mcpSessionsUrl } from './sessionUrls'

describe('MCP session URLs', () => {
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

    it('links a session through the shared property filters', () => {
        expect(mcpSessionUrl('linked-session', { ...sharedParams, search: 'old-session' })).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), {
                ...sharedParams,
                properties: [toolFilter, sessionFilter('linked-session')],
            }).url
        )
    })

    it('opens the full session list without stale session filters', () => {
        expect(mcpSessionsUrl({ ...sharedParams, search: 'old-session' })).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), { ...sharedParams, properties: [toolFilter] }).url
        )
    })
})
