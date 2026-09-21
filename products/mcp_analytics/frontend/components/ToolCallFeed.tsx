import { LemonTag, Link } from '@posthog/lemon-ui'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'

import { mcpSessionUrl } from '../tool-quality/errorContext'
import {
    MCP_ACTIVITY_ERROR_COLUMN,
    MCP_ACTIVITY_INTENT_COLUMN,
    MCP_ACTIVITY_MAX_ROWS,
    MCP_ACTIVITY_SESSION_COLUMN,
} from './toolCallFeedQuery'

function IntentCell({ value }: { value: unknown }): JSX.Element {
    return <span className="block min-w-64 whitespace-normal">{value ? String(value) : '—'}</span>
}

// SDK versions stamp $mcp_is_error as a boolean, the string 'true', or 1; the backend treats all three as failures.
export const MCP_ERROR_VALUES: ReadonlyArray<unknown> = [true, 'true', 1, '1']

function ErrorCell({ value }: { value: unknown }): JSX.Element {
    const failed = MCP_ERROR_VALUES.includes(value)
    return failed ? (
        <LemonTag type="danger" size="small">
            Failed
        </LemonTag>
    ) : (
        <span className="text-muted">OK</span>
    )
}

function SessionCell({ value }: { value: unknown }): JSX.Element {
    if (!value) {
        return <span className="text-muted">—</span>
    }
    return (
        <Link to={mcpSessionUrl(String(value))} data-attr="mcp-analytics-activity-session-link">
            View session
        </Link>
    )
}

/** The MCP tool-call events table with its cell renderers, shared by the activity feed and the dashboard glance. */
export function ToolCallFeed({
    query,
    setQuery,
    uniqueKey,
    dataNodeCollectionId,
    attachTo,
    maxRows = MCP_ACTIVITY_MAX_ROWS,
}: {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    uniqueKey: string
    dataNodeCollectionId?: string
    attachTo?: Parameters<typeof Query>[0]['attachTo']
    /** Rows the table may page up to; at the query's own limit, "load more" never shows. */
    maxRows?: number
}): JSX.Element {
    return (
        <Query
            attachTo={attachTo}
            uniqueKey={uniqueKey}
            query={query}
            setQuery={setQuery}
            context={{
                dataTableMaxPaginationRows: maxRows,
                dataTableAllowContentScroll: true,
                dataTableNouns: ['tool call', 'tool calls'],
                compactDataTableToolbar: true,
                hideRecordingButton: true,
                columns: {
                    [MCP_ACTIVITY_INTENT_COLUMN]: { render: IntentCell, width: '20rem' },
                    [MCP_ACTIVITY_ERROR_COLUMN]: { render: ErrorCell, title: 'Result' },
                    [MCP_ACTIVITY_SESSION_COLUMN]: { render: SessionCell },
                },
                emptyStateDetail: 'Adjust the date range or filters, or wait for agents to call a tool.',
                emptyStateHeading: 'No MCP tool calls in this period',
                extraDataTableQueryFeatures: [QueryFeature.showCount],
                insightProps: {
                    dashboardItemId: `new-${uniqueKey}`,
                    dataNodeCollectionId,
                },
                showOpenEditorButton: false,
            }}
        />
    )
}
