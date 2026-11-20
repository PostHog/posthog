import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { renderHogQLX } from '~/queries/nodes/HogQLX/render'
import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpSessionUrl } from '../sessionUrls'
import { NotCaptured } from './NotCaptured'
import {
    MCP_ACTIVITY_DURATION_COLUMN,
    MCP_ACTIVITY_ERROR_COLUMN,
    MCP_ACTIVITY_INTENT_COLUMN,
    MCP_ACTIVITY_MAX_ROWS,
    MCP_ACTIVITY_MODEL_COLUMN,
    MCP_ACTIVITY_SESSION_COLUMN,
} from './toolCallFeedQuery'

function IntentCell({ value }: { value: unknown }): JSX.Element {
    if (!value) {
        return (
            <NotCaptured reason="The agent didn't say what it was trying to do." fix={INSTRUMENTATION_FIXES.intent} />
        )
    }
    return <span className="block min-w-64 whitespace-normal">{String(value)}</span>
}

// The cell is rendered; read the raw model from the row's event.
function ModelCell({ value, record }: { value: unknown; record: unknown }): JSX.Element {
    const event = Array.isArray(record) ? record[0] : null
    if (event?.properties && !event.properties.$mcp_llm_model) {
        return (
            <NotCaptured reason="This call arrived without the model that made it." fix={INSTRUMENTATION_FIXES.model} />
        )
    }
    return renderHogQLX(value)
}

function ErrorCell({ value }: { value: unknown }): JSX.Element | null {
    return value ? (
        <LemonTag type="danger" size="small" className="font-mono">
            {String(value)}
        </LemonTag>
    ) : null
}

function DurationCell({ value }: { value: unknown }): JSX.Element {
    const { slowThresholdMs } = useValues(mcpAnalyticsFiltersLogic)
    if (value === null || value === undefined || value === '') {
        return <span className="text-muted">—</span>
    }
    const ms = Number(value)
    if (slowThresholdMs === null || !(ms > slowThresholdMs)) {
        return <span className="tabular-nums">{ms.toLocaleString()}</span>
    }
    return (
        <Tooltip title={`Slow: over the ${slowThresholdMs.toLocaleString()} ms p95 of all calls`}>
            <LemonTag type="warning" size="small" className="tabular-nums">
                {ms.toLocaleString()}
            </LemonTag>
        </Tooltip>
    )
}

function SessionCell({ value }: { value: unknown }): JSX.Element {
    const { searchParams } = useValues(router)
    if (!value) {
        return <span className="text-muted">—</span>
    }
    return (
        <Link to={mcpSessionUrl(String(value), searchParams)} data-attr="mcp-analytics-activity-session-link">
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
    rowProps,
}: {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Also the data node key, so the drawer can read loaded rows. */
    uniqueKey: string
    dataNodeCollectionId?: string
    attachTo?: Parameters<typeof Query>[0]['attachTo']
    /** Rows the table may page up to; at the query's own limit, "load more" never shows. */
    maxRows?: number
    rowProps?: QueryContext['rowProps']
}): JSX.Element {
    return (
        <Query
            attachTo={attachTo}
            uniqueKey={uniqueKey}
            query={query}
            setQuery={setQuery}
            context={{
                dataNodeLogicKey: uniqueKey,
                rowProps,
                dataTableMaxPaginationRows: maxRows,
                dataTableNouns: ['tool call', 'tool calls'],
                compactDataTableToolbar: true,
                hideRecordingButton: true,
                columns: {
                    [MCP_ACTIVITY_INTENT_COLUMN]: { render: IntentCell, width: '20rem' },
                    [MCP_ACTIVITY_ERROR_COLUMN]: { render: ErrorCell, title: 'Error' },
                    [MCP_ACTIVITY_DURATION_COLUMN]: { render: DurationCell, align: 'right' },
                    [MCP_ACTIVITY_MODEL_COLUMN]: { render: ModelCell },
                    [MCP_ACTIVITY_SESSION_COLUMN]: { render: SessionCell },
                },
                emptyStateDetail: 'Adjust the date range or filters, or wait for agents to call a tool.',
                emptyStateHeading: 'No MCP tool calls in this period',
                insightProps: {
                    dashboardItemId: `new-${uniqueKey}`,
                    dataNodeCollectionId,
                },
                showOpenEditorButton: false,
            }}
        />
    )
}
