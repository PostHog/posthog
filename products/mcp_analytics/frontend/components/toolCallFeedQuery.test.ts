import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    DEFAULT_MCP_ACTIVITY_QUERY,
    MCP_ACTIVITY_COLUMNS,
    MCP_ACTIVITY_MAX_ROWS,
    MCP_ACTIVITY_PAGE_SIZE,
    MCP_RECENT_TOOL_CALLS_LIMIT,
    buildRecentToolCallsQuery,
} from './toolCallFeedQuery'

describe('tool call feed queries', () => {
    it('starts the expandable MCP activity feed at 100 rows with room to load more', () => {
        expect(DEFAULT_MCP_ACTIVITY_QUERY).toMatchObject({
            embedded: false,
            expandable: true,
            showCount: true,
            showDateRange: true,
            showPropertyFilter: expect.any(Array),
            source: {
                events: ['$mcp_tool_call'],
                limit: 100,
                orderBy: ['timestamp DESC'],
            },
        })
        expect(MCP_ACTIVITY_PAGE_SIZE).toBe(100)
        expect(MCP_ACTIVITY_MAX_ROWS).toBeGreaterThan(MCP_ACTIVITY_PAGE_SIZE)
        expect(MCP_ACTIVITY_COLUMNS).toContain('*')
        expect(MCP_ACTIVITY_COLUMNS.find((column) => column.endsWith('-- Tool'))).toContain('$mcp_exec_tool_call_name')
    })

    it('scopes the dashboard glance to the dashboard filters and drops the toolbar', () => {
        const toolFilter: AnyPropertyFilter = {
            key: '$mcp_tool_name',
            value: ['search'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }

        const query = buildRecentToolCallsQuery({
            dateRange: { date_from: '-7d', date_to: '-1d' },
            properties: [toolFilter],
            filterTestAccounts: true,
        })

        expect(query).toMatchObject({
            embedded: false,
            showDateRange: false,
            showPropertyFilter: false,
            showReload: false,
            source: {
                select: MCP_ACTIVITY_COLUMNS,
                after: '-7d',
                before: '-1d',
                properties: [toolFilter],
                filterTestAccounts: true,
                limit: MCP_RECENT_TOOL_CALLS_LIMIT,
            },
        })
    })
})
