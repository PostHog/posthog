import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { LLMTrace } from '~/queries/schema/schema-general'
import { QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

import { llmObservabilityLogic } from './llmObservabilityLogic'
import { formatLLMCost, formatLLMUsage, removeMilliseconds } from './utils'

export function LLMObservabilityTraces(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setTracesQuery } =
        useActions(llmObservabilityLogic)
    const { tracesQuery } = useValues(llmObservabilityLogic)
    return (
        <DataTable
            query={tracesQuery}
            setQuery={(query) => {
                if (!isTracesQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.dateRange?.date_from || null, query.source.dateRange?.date_to || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                setPropertyFilters(query.source.properties || [])
                setTracesQuery(query)
            }}
            context={{
                emptyStateHeading: 'There were no traces in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    id: {
                        title: 'ID',
                        render: IDColumn,
                    },
                    timestamp: {
                        title: 'Time',
                        render: TimestampColumn,
                    },
                    traceName: {
                        title: 'Trace Name',
                        render: TraceNameColumn,
                    },
                    person: {
                        title: 'Person',
                    },
                    totalLatency: {
                        title: 'Latency',
                        render: LatencyColumn,
                    },
                    usage: {
                        title: 'Token Usage',
                        render: UsageColumn,
                    },
                    totalCost: {
                        title: 'Total Cost',
                        render: CostColumn,
                    },
                },
            }}
            uniqueKey="llm-observability-traces"
        />
    )
}

const IDColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return (
        <strong>
            <Tooltip title={row.id}>
                <Link
                    className="ph-no-capture"
                    to={urls.llmObservabilityTrace(row.id, { timestamp: removeMilliseconds(row.createdAt) })}
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
        <strong>
            <Link
                className="ph-no-capture"
                to={urls.llmObservabilityTrace(row.id, { timestamp: removeMilliseconds(row.createdAt) })}
            >
                {row.traceName || '–'}
            </Link>
        </strong>
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
        return <>{row.totalLatency}s</>
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
