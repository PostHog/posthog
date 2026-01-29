import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, LLMTrace } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { llmAnalyticsColumnRenderers } from './llmAnalyticsColumnRenderers'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsTracesTabLogic } from './tabs/llmAnalyticsTracesTabLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage, getTraceTimestamp, normalizeMessages } from './utils'

export function LLMAnalyticsTraces(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setShouldFilterSupportTraces, setPropertyFilters } =
        useActions(llmAnalyticsSharedLogic)
    const { propertyFilters: currentPropertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { tracesQuery } = useValues(llmAnalyticsTracesTabLogic)

    return (
        <div data-attr="llm-trace-table">
            <DataTable
                query={{
                    ...tracesQuery,
                    showSavedFilters: true,
                }}
                setQuery={(query) => {
                    if (!isTracesQuery(query.source)) {
                        throw new Error('Invalid query')
                    }
                    setDates(query.source.dateRange?.date_from || null, query.source.dateRange?.date_to || null)
                    setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                    setShouldFilterSupportTraces(query.source.filterSupportTraces ?? true)

                    const newPropertyFilters = query.source.properties || []
                    if (!objectsEqual(newPropertyFilters, currentPropertyFilters)) {
                        setPropertyFilters(newPropertyFilters)
                    }
                }}
                context={useTracesQueryContext()}
                uniqueKey="llm-analytics-traces"
            />
        </div>
    )
}

export const useTracesQueryContext = (): QueryContext<DataTableNode> => {
    return {
        emptyStateHeading: 'There were no traces in this period',
        emptyStateDetail: 'Try changing the date range or filters.',
        columns: {
            id: {
                title: 'ID',
                render: IDColumn,
            },
            inputState: {
                title: 'Input message',
                render: InputMessageColumn,
            },
            outputState: {
                title: 'Output message',
                render: OutputMessageColumn,
            },
            timestamp: {
                title: 'Time',
                render: TimestampColumn,
            },
            traceName: {
                title: 'Trace Name',
                render: TraceNameColumn,
            },
            person: llmAnalyticsColumnRenderers.person,
            errors: {
                renderTitle: () => <Tooltip title="Number of errors in this trace">Errors</Tooltip>,
                render: ErrorsColumn,
            },
            totalLatency: {
                renderTitle: () => <Tooltip title="Total latency of all operations in this trace">Latency</Tooltip>,
                render: LatencyColumn,
            },
            usage: {
                renderTitle: () => (
                    <Tooltip title="Total token usage (input + output) for this trace">Token Usage</Tooltip>
                ),
                render: UsageColumn,
            },
            totalCost: {
                renderTitle: () => (
                    <Tooltip title="Total cost of all generations and embeddings in this trace">Cost</Tooltip>
                ),
                render: CostColumn,
            },
        },
    }
}

const IDColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return (
        <strong>
            <Tooltip title={row.id}>
                <Link
                    to={urls.llmAnalyticsTrace(row.id, { timestamp: getTraceTimestamp(row.createdAt) })}
                    data-attr="trace-id-link"
                >
                    {row.id.slice(0, 4)}...{row.id.slice(-4)}
                </Link>
            </Tooltip>
        </strong>
    )
}

const TraceNameColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return (
        <div className="flex items-center gap-2">
            <strong>
                <Link
                    to={urls.llmAnalyticsTrace(row.id, { timestamp: getTraceTimestamp(row.createdAt) })}
                    data-attr="trace-name-link"
                >
                    {row.traceName || '–'}
                </Link>
            </strong>
            {row.isSupportTrace && <LemonTag type="muted">Support</LemonTag>}
        </div>
    )
}

const TimestampColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return <TZLabel time={row.createdAt} />
}
TimestampColumn.displayName = 'TimestampColumn'

const LatencyColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalLatency === 'number') {
        return <>{formatLLMLatency(row.totalLatency, true)}</>
    }
    return <>–</>
}
LatencyColumn.displayName = 'LatencyColumn'

const UsageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const usage = formatLLMUsage(row)
    return <>{usage || '–'}</>
}
UsageColumn.displayName = 'UsageColumn'

const CostColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalCost === 'number') {
        return <>{formatLLMCost(row.totalCost)}</>
    }
    return <>–</>
}
CostColumn.displayName = 'CostColumn'

const ErrorsColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.errorCount === 'number' && row.errorCount > 0) {
        return <LemonTag type="danger">{row.errorCount}</LemonTag>
    }
    return <>–</>
}
ErrorsColumn.displayName = 'ErrorsColumn'

const InputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const inputNormalized = normalizeMessages(row.inputState?.messages, 'user')
    if (!inputNormalized.length) {
        return <>–</>
    }
    return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
}
InputMessageColumn.displayName = 'InputMessageColumn'

const OutputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const errorEventFound = Array.isArray(row.events)
        ? row.events.find((e) => e.properties?.$ai_error || e.properties?.$ai_is_error)
        : false
    if (errorEventFound) {
        return (
            <LemonTag type="danger" className="font-mono max-w-50 truncate">
                {errorEventFound.properties?.$ai_error || 'Unknown error'}
            </LemonTag>
        )
    }
    const outputNormalized = normalizeMessages(row.outputState?.messages, 'assistant')
    if (!outputNormalized.length) {
        return <>–</>
    }
    return <LLMMessageDisplay message={outputNormalized.at(-1)!} isOutput={true} minimal />
}
OutputMessageColumn.displayName = 'OutputMessageColumn'
