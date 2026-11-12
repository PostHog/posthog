import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    DEFAULT_MCP_ACTIVITY_QUERY,
    MCP_ACTIVITY_COLUMNS,
    MCP_ACTIVITY_MAX_ROWS,
    MCP_ACTIVITY_PAGE_SIZE,
    withFailedCallsOnly,
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
        expect(MCP_ACTIVITY_COLUMNS.find((column) => column.endsWith('-- Model'))).toContain('$mcp_llm_model')
    })

    it('narrows the feed to failed calls without dropping other filters or stacking itself', () => {
        const toolFilter: AnyPropertyFilter = {
            key: '$mcp_tool_name',
            value: ['search'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }
        // Same key on a person property is a different filter and must survive.
        const personFilter: AnyPropertyFilter = {
            key: '$mcp_is_error',
            value: ['true'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Person,
        }
        const query: DataTableNode = {
            ...DEFAULT_MCP_ACTIVITY_QUERY,
            source: { ...(DEFAULT_MCP_ACTIVITY_QUERY.source as EventsQuery), properties: [toolFilter, personFilter] },
        }

        const once = withFailedCallsOnly(query)
        const twice = withFailedCallsOnly(once)

        expect(once.source.kind).toBe(NodeKind.EventsQuery)
        expect(twice.source).toMatchObject({
            properties: [toolFilter, personFilter, { key: '$mcp_is_error', value: ['true', '1'] }],
        })
    })
})
