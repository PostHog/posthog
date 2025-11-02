import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { LLMTrace, NodeKind, TraceQuery, TracesQuery } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

import { LLMAnalyticsTraceEvents } from './components/LLMAnalyticsTraceEvents'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'
import { formatLLMCost } from './utils'

export function LLMAnalyticsSessions(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setSessionsSort } = useActions(llmAnalyticsLogic)
    const { sessionsQuery, dateFilter, sessionsSort } = useValues(llmAnalyticsLogic)
    const [expandedSessionIds, setExpandedSessionIds] = useState<Set<string>>(new Set())
    const [expandedTraceIds, setExpandedTraceIds] = useState<Set<string>>(new Set())
    const [expandedGenerationIds, setExpandedGenerationIds] = useState<Set<string>>(new Set())
    const [sessionTraces, setSessionTraces] = useState<Record<string, LLMTrace[]>>({})
    const [loadingTraces, setLoadingTraces] = useState<Set<string>>(new Set())
    const [loadingFullTraces, setLoadingFullTraces] = useState<Set<string>>(new Set())
    const [fullTraces, setFullTraces] = useState<Record<string, LLMTrace>>({})

    const handleSessionExpand = async (sessionId: string): Promise<void> => {
        const newExpanded = new Set(expandedSessionIds)
        if (newExpanded.has(sessionId)) {
            newExpanded.delete(sessionId)
            setExpandedSessionIds(newExpanded)
        } else {
            newExpanded.add(sessionId)
            setExpandedSessionIds(newExpanded)

            // Load traces for this session if not already loaded
            if (!sessionTraces[sessionId] && !loadingTraces.has(sessionId)) {
                setLoadingTraces(new Set(loadingTraces).add(sessionId))

                const tracesQuerySource: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || undefined,
                        date_to: dateFilter.dateTo || undefined,
                    },
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$ai_session_id',
                            operator: 'exact' as any,
                            value: sessionId,
                        },
                    ],
                }

                try {
                    const response = await api.query(tracesQuerySource)
                    if (response.results) {
                        setSessionTraces((prev) => ({
                            ...prev,
                            [sessionId]: response.results,
                        }))
                    }
                } catch (error) {
                    console.error('Error loading traces for session:', error)
                } finally {
                    const newLoading = new Set(loadingTraces)
                    newLoading.delete(sessionId)
                    setLoadingTraces(newLoading)
                }
            }
        }
    }

    const handleGenerationExpand = (generationId: string): void => {
        const newExpanded = new Set(expandedGenerationIds)
        if (newExpanded.has(generationId)) {
            newExpanded.delete(generationId)
        } else {
            newExpanded.add(generationId)
        }
        setExpandedGenerationIds(newExpanded)
    }

    const handleColumnClick = (column: string): void => {
        // Toggle sort direction if clicking same column, otherwise default to DESC
        const newDirection = sessionsSort.column === column && sessionsSort.direction === 'DESC' ? 'ASC' : 'DESC'
        setSessionsSort(column, newDirection)
    }

    const renderSortableColumnTitle = (column: string, title: string): JSX.Element => {
        const isSorted = sessionsSort.column === column
        const direction = sessionsSort.direction
        return (
            <span
                onClick={() => handleColumnClick(column)}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                className="flex items-center gap-1"
            >
                {title}
                {isSorted && (direction === 'DESC' ? ' ▼' : ' ▲')}
            </span>
        )
    }

    const handleTraceExpand = async (traceId: string): Promise<void> => {
        const newExpanded = new Set(expandedTraceIds)
        if (newExpanded.has(traceId)) {
            newExpanded.delete(traceId)
            setExpandedTraceIds(newExpanded)
        } else {
            newExpanded.add(traceId)
            setExpandedTraceIds(newExpanded)

            // Load full trace with events if not already loaded
            if (!fullTraces[traceId] && !loadingFullTraces.has(traceId)) {
                setLoadingFullTraces(new Set(loadingFullTraces).add(traceId))

                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    dateRange: {
                        date_from: dateFilter.dateFrom || undefined,
                        date_to: dateFilter.dateTo || undefined,
                    },
                }

                try {
                    const response = await api.query(traceQuery)
                    if (response.results && response.results[0]) {
                        setFullTraces((prev) => ({
                            ...prev,
                            [traceId]: response.results[0],
                        }))
                    }
                } catch (error) {
                    console.error('Error loading full trace:', error)
                } finally {
                    const newLoading = new Set(loadingFullTraces)
                    newLoading.delete(traceId)
                    setLoadingFullTraces(newLoading)
                }
            }
        }
    }

    return (
        <DataTable
            query={{
                ...sessionsQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMAnalyticsSessions received a non-HogQL query:', query.source)
                    return
                }
                const { filters = {} } = query.source
                const { dateRange = {} } = filters
                setDates(dateRange.date_from || null, dateRange.date_to || null)
                setShouldFilterTestAccounts(filters.filterTestAccounts || false)
                setPropertyFilters(filters.properties || [])
            }}
            context={{
                emptyStateHeading: 'There were no AI sessions in this period',
                emptyStateDetail: (
                    <>
                        Try changing the date range or filters. AI sessions require the <code>$ai_session_id</code>{' '}
                        property to group related traces.{' '}
                        <Link to="https://posthog.com/docs/llm-analytics/sessions" target="_blank">
                            Learn more →
                        </Link>
                    </>
                ),
                columns: {
                    session_id: {
                        title: 'Session ID',
                        render: function RenderSessionId(x) {
                            const sessionId = x.value as string
                            const truncated = `${sessionId.slice(0, 4)}...${sessionId.slice(-4)}`
                            const sessionUrl = `${urls.llmAnalyticsSession(sessionId)}?${new URLSearchParams({
                                ...(dateFilter.dateFrom && { date_from: dateFilter.dateFrom }),
                                ...(dateFilter.dateTo && { date_to: dateFilter.dateTo }),
                            }).toString()}`
                            return (
                                <strong>
                                    <Tooltip title={sessionId}>
                                        <Link className="ph-no-capture font-mono" to={sessionUrl}>
                                            {truncated}
                                        </Link>
                                    </Tooltip>
                                </strong>
                            )
                        },
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of traces in this session">
                                {renderSortableColumnTitle('traces', 'Traces')}
                            </Tooltip>
                        ),
                    },
                    spans: {
                        renderTitle: () => (
                            <Tooltip title="Number of spans in this session">
                                {renderSortableColumnTitle('spans', 'Spans')}
                            </Tooltip>
                        ),
                    },
                    generations: {
                        renderTitle: () => (
                            <Tooltip title="Number of generations in this session">
                                {renderSortableColumnTitle('generations', 'Generations')}
                            </Tooltip>
                        ),
                    },
                    errors: {
                        renderTitle: () => (
                            <Tooltip title="Number of errors in this session">
                                {renderSortableColumnTitle('errors', 'Errors')}
                            </Tooltip>
                        ),
                    },
                    total_cost: {
                        renderTitle: () => (
                            <Tooltip title="Total cost of all generations in this session">
                                {renderSortableColumnTitle('total_cost', 'Cost')}
                            </Tooltip>
                        ),
                        render: function RenderCost({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>{formatLLMCost(Number(value))}</span>
                        },
                    },
                    total_latency: {
                        renderTitle: () => (
                            <Tooltip title="Total latency of all generations in this session">
                                {renderSortableColumnTitle('total_latency', 'Latency')}
                            </Tooltip>
                        ),
                        render: function RenderLatency({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>{Number(value).toFixed(2)} s</span>
                        },
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First Seen'),
                        render: function RenderFirstSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last Seen'),
                        render: function RenderLastSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                },
                expandable: {
                    expandedRowRender: function renderExpandedSession({ result }: DataTableRow) {
                        if (!Array.isArray(result) || result.length === 0) {
                            return null
                        }

                        const sessionId = result[0] as string
                        const traces = sessionTraces[sessionId]
                        const isLoading = loadingTraces.has(sessionId)

                        if (isLoading) {
                            return (
                                <div className="p-4">
                                    <Spinner />
                                </div>
                            )
                        }

                        if (!traces || traces.length === 0) {
                            return <div className="p-4">No traces found for this session</div>
                        }

                        return (
                            <div className="pt-2 px-4 pb-4">
                                <div className="space-y-2">
                                    {traces.map((trace) => {
                                        const isTraceExpanded = expandedTraceIds.has(trace.id)

                                        return (
                                            <div key={trace.id} className="border rounded">
                                                <div
                                                    className="p-3 hover:bg-side-light cursor-pointer flex items-start gap-2"
                                                    onClick={() => handleTraceExpand(trace.id)}
                                                >
                                                    <div className="flex-shrink-0 mt-0.5">
                                                        {isTraceExpanded ? (
                                                            <IconChevronDown className="text-lg" />
                                                        ) : (
                                                            <IconChevronRight className="text-lg" />
                                                        )}
                                                    </div>
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                                                            <strong className="font-mono text-xs">
                                                                {trace.id.slice(0, 8)}...
                                                            </strong>
                                                            {trace.traceName && (
                                                                <span className="text-sm">{trace.traceName}</span>
                                                            )}
                                                            {trace.errorCount && trace.errorCount > 0 && (
                                                                <LemonTag type="danger" size="small">
                                                                    {trace.errorCount === 1
                                                                        ? '1 error'
                                                                        : `${trace.errorCount} errors`}
                                                                </LemonTag>
                                                            )}
                                                            {typeof trace.totalLatency === 'number' && (
                                                                <LemonTag type="muted">
                                                                    {trace.totalLatency.toFixed(2)}s
                                                                </LemonTag>
                                                            )}
                                                            {typeof trace.totalCost === 'number' && (
                                                                <LemonTag type="muted">
                                                                    {formatLLMCost(trace.totalCost)}
                                                                </LemonTag>
                                                            )}
                                                            <Link
                                                                to={urls.llmAnalyticsTrace(trace.id)}
                                                                onClick={(e) => e.stopPropagation()}
                                                                className="text-xs"
                                                            >
                                                                View full trace →
                                                            </Link>
                                                        </div>
                                                        <div className="text-xs text-muted">
                                                            <TZLabel time={trace.createdAt} />
                                                        </div>
                                                    </div>
                                                </div>
                                                {isTraceExpanded && (
                                                    <div className="border-t bg-bg-light">
                                                        <div className="p-3 space-y-2">
                                                            <LLMAnalyticsTraceEvents
                                                                trace={fullTraces[trace.id]}
                                                                isLoading={loadingFullTraces.has(trace.id)}
                                                                expandedEventIds={expandedGenerationIds}
                                                                onToggleEventExpand={handleGenerationExpand}
                                                            />
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )
                    },
                    rowExpandable: ({ result }: DataTableRow) =>
                        !!result && Array.isArray(result) && result.length > 0 && !!result[0],
                    isRowExpanded: ({ result }: DataTableRow) =>
                        Array.isArray(result) && !!result[0] && expandedSessionIds.has(result[0] as string),
                    onRowExpand: ({ result }: DataTableRow) => {
                        if (Array.isArray(result) && result[0]) {
                            handleSessionExpand(result[0] as string)
                        }
                    },
                    onRowCollapse: ({ result }: DataTableRow) => {
                        if (Array.isArray(result) && result[0]) {
                            handleSessionExpand(result[0] as string)
                        }
                    },
                    noIndent: true,
                },
            }}
            uniqueKey="llm-analytics-sessions"
        />
    )
}
