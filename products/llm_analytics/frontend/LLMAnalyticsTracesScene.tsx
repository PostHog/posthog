import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { LLMTrace } from '~/queries/schema/schema-general'
import { QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'
import { tracesReviewLogic } from './tracesReviewLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage, normalizeMessages, removeMilliseconds } from './utils'

export function LLMAnalyticsTraces(): JSX.Element {
    return <LLMAnalyticsTracesWithReviews />
}

function LLMAnalyticsTracesWithReviews(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setTracesQuery } = useActions(llmAnalyticsLogic)
    const { loadBatchReviewStatuses } = useActions(tracesReviewLogic)
    const { getReviewStatus, isTraceReviewed } = useValues(tracesReviewLogic)

    const { tracesQuery } = useValues(llmAnalyticsLogic)

    // Store the IDColumn component with review logic injected
    const IDColumnWithReviews = useMemo(
        () =>
            ({ record }: { record: any }) => (
                <IDColumn record={record} getReviewStatus={getReviewStatus} isTraceReviewed={isTraceReviewed} />
            ),
        [getReviewStatus, isTraceReviewed]
    )

    // Extract trace IDs from query response data and load review statuses
    const handleDataLoaded = useMemo(
        () => (data: Record<string, unknown> | null | undefined) => {
            if (data && Array.isArray(data.results)) {
                const traceIds = data.results.filter((trace: any) => trace?.id).map((trace: any) => trace.id)

                if (traceIds.length > 0) {
                    loadBatchReviewStatuses(traceIds)
                }
            }
        },
        [loadBatchReviewStatuses]
    )

    return (
        <TracesDataTableWithReviews
            tracesQuery={tracesQuery}
            IDColumnWithReviews={IDColumnWithReviews}
            onDataLoaded={handleDataLoaded}
            setDates={setDates}
            setShouldFilterTestAccounts={setShouldFilterTestAccounts}
            setPropertyFilters={setPropertyFilters}
            setTracesQuery={setTracesQuery}
        />
    )
}

interface TracesDataTableProps {
    tracesQuery: any
    IDColumnWithReviews: any
    onDataLoaded: (data: Record<string, unknown> | null | undefined) => void
    setDates: (from: string | null, to: string | null) => void
    setShouldFilterTestAccounts: (filter: boolean) => void
    setPropertyFilters: (filters: any[]) => void
    setTracesQuery: (query: any) => void
}

function TracesDataTableWithReviews({
    tracesQuery,
    IDColumnWithReviews,
    onDataLoaded,
    setDates,
    setShouldFilterTestAccounts,
    setPropertyFilters,
    setTracesQuery,
}: TracesDataTableProps): JSX.Element {
    // Create a unique key to ensure proper dataNodeLogic connection
    const dataNodeKey = useMemo(() => `traces-table-${Date.now()}`, [])

    return (
        <DataTable
            query={{
                ...tracesQuery,
                showSavedFilters: true,
            }}
            dataNodeLogicKey={dataNodeKey}
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
                insightProps: {
                    dashboardItemId: undefined,
                    onData: onDataLoaded,
                },
                columns: {
                    id: {
                        title: 'ID',
                        render: IDColumnWithReviews,
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
            uniqueKey="llm-analytics-traces"
        />
    )
}

interface IDColumnProps {
    record: any
    getReviewStatus: (traceId: string) => any
    isTraceReviewed: (traceId: string) => boolean
}

const IDColumn = ({ record, getReviewStatus, isTraceReviewed }: IDColumnProps): JSX.Element => {
    const row = record as LLMTrace

    const isReviewed = isTraceReviewed(row.id)
    const reviewData = getReviewStatus(row.id)

    const reviewTooltip = reviewData ? (
        <div className="space-y-1">
            <div className="text-xs text-muted-alt">Reviewed by</div>
            <div className="flex items-center gap-2">
                <PersonDisplay
                    person={{
                        distinct_id: String(reviewData.reviewed_by.id),
                        properties: {
                            email: reviewData.reviewed_by.email,
                            first_name: reviewData.reviewed_by.first_name,
                        },
                    }}
                    withIcon="sm"
                    noPopover
                    noLink
                />
            </div>
            <div className="text-xs text-muted-alt">
                <TZLabel time={reviewData.reviewed_at} />
            </div>
        </div>
    ) : (
        'This trace has been reviewed'
    )

    return (
        <div className="flex items-center gap-1.5">
            <strong className={isReviewed ? 'opacity-[var(--opacity-disabled)]' : ''}>
                <Tooltip title={row.id}>
                    <Link
                        className="ph-no-capture"
                        to={urls.llmAnalyticsTrace(row.id, { timestamp: removeMilliseconds(row.createdAt) })}
                    >
                        {row.id.slice(0, 4)}...{row.id.slice(-4)}
                    </Link>
                </Tooltip>
            </strong>
            {isReviewed && (
                <Tooltip title={reviewTooltip}>
                    <IconCheck className="text-success size-4 shrink-0" />
                </Tooltip>
            )}
        </div>
    )
}

const TraceNameColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return (
        <strong>
            <Link
                className="ph-no-capture"
                to={urls.llmAnalyticsTrace(row.id, { timestamp: removeMilliseconds(row.createdAt) })}
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
