import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { LLMTrace, NodeKind, TraceQuery, TracesQuery } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { EventType, PropertyFilterType } from '~/types'

import { llmAnalyticsLogic } from './llmAnalyticsLogic'
import { formatLLMCost } from './utils'

export function LLMAnalyticsSessions(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsLogic)
    const { sessionsQuery, dateFilter } = useValues(llmAnalyticsLogic)
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
                        setSessionTraces({
                            ...sessionTraces,
                            [sessionId]: response.results,
                        })
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
                        setFullTraces({
                            ...fullTraces,
                            [traceId]: response.results[0],
                        })
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
                columns: {
                    session_id: {
                        title: 'Session ID',
                        render: function RenderSessionId(x) {
                            const sessionId = x.value as string
                            const truncated =
                                sessionId.length > 16 ? `${sessionId.slice(0, 8)}...${sessionId.slice(-8)}` : sessionId
                            return (
                                <strong>
                                    <Tooltip title={sessionId}>
                                        <Link
                                            className="ph-no-capture font-mono"
                                            to={urls.llmAnalyticsSession(sessionId)}
                                        >
                                            {truncated}
                                        </Link>
                                    </Tooltip>
                                </strong>
                            )
                        },
                    },
                    traces: {
                        title: 'Traces',
                    },
                    generations: {
                        title: 'Generations',
                    },
                    errors: {
                        title: 'Errors',
                    },
                    total_cost: {
                        title: 'Total cost',
                        render: function RenderCost({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>{formatLLMCost(Number(value))}</span>
                        },
                    },
                    total_latency: {
                        title: 'Total latency',
                        render: function RenderLatency({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>{Number(value).toFixed(2)} s</span>
                        },
                    },
                    first_seen: {
                        title: 'First Seen',
                        render: function RenderFirstSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                    last_seen: {
                        title: 'Last Seen',
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
                                                            {loadingFullTraces.has(trace.id) ? (
                                                                <Spinner />
                                                            ) : fullTraces[trace.id] ? (
                                                                (() => {
                                                                    const fullTrace = fullTraces[trace.id]
                                                                    const generationEvents =
                                                                        fullTrace.events?.filter(
                                                                            (e) => e.event === '$ai_generation'
                                                                        ) || []

                                                                    return generationEvents.length > 0 ? (
                                                                        <>
                                                                            <div className="text-xs font-semibold text-muted uppercase">
                                                                                Generations ({generationEvents.length})
                                                                            </div>
                                                                            {generationEvents.map((event) => {
                                                                                const eventForDetails: EventType = {
                                                                                    id: event.id,
                                                                                    distinct_id: '',
                                                                                    properties: event.properties,
                                                                                    event: event.event,
                                                                                    timestamp: event.createdAt,
                                                                                    elements: [],
                                                                                }
                                                                                const isGenerationExpanded =
                                                                                    expandedGenerationIds.has(event.id)
                                                                                const model =
                                                                                    event.properties.$ai_model ||
                                                                                    'Unknown model'
                                                                                const latency =
                                                                                    event.properties.$ai_latency
                                                                                const cost =
                                                                                    event.properties.$ai_total_cost_usd

                                                                                return (
                                                                                    <div
                                                                                        key={event.id}
                                                                                        className="border rounded bg-bg-3000"
                                                                                    >
                                                                                        <div
                                                                                            className="p-2 hover:bg-side-light cursor-pointer flex items-center gap-2"
                                                                                            onClick={() =>
                                                                                                handleGenerationExpand(
                                                                                                    event.id
                                                                                                )
                                                                                            }
                                                                                        >
                                                                                            <div className="flex-shrink-0">
                                                                                                {isGenerationExpanded ? (
                                                                                                    <IconChevronDown className="text-base" />
                                                                                                ) : (
                                                                                                    <IconChevronRight className="text-base" />
                                                                                                )}
                                                                                            </div>
                                                                                            <div className="flex-1 flex items-center gap-2 flex-wrap min-w-0">
                                                                                                <LemonTag
                                                                                                    type="success"
                                                                                                    size="small"
                                                                                                    className="uppercase"
                                                                                                >
                                                                                                    Generation
                                                                                                </LemonTag>
                                                                                                <span className="text-xs truncate">
                                                                                                    {model}
                                                                                                </span>
                                                                                                {typeof latency ===
                                                                                                    'number' && (
                                                                                                    <LemonTag
                                                                                                        type="muted"
                                                                                                        size="small"
                                                                                                    >
                                                                                                        {latency.toFixed(
                                                                                                            2
                                                                                                        )}
                                                                                                        s
                                                                                                    </LemonTag>
                                                                                                )}
                                                                                                {typeof cost ===
                                                                                                    'number' && (
                                                                                                    <LemonTag
                                                                                                        type="muted"
                                                                                                        size="small"
                                                                                                    >
                                                                                                        {formatLLMCost(
                                                                                                            cost
                                                                                                        )}
                                                                                                    </LemonTag>
                                                                                                )}
                                                                                            </div>
                                                                                        </div>
                                                                                        {isGenerationExpanded && (
                                                                                            <div className="border-t">
                                                                                                <EventDetails
                                                                                                    event={
                                                                                                        eventForDetails
                                                                                                    }
                                                                                                />
                                                                                            </div>
                                                                                        )}
                                                                                    </div>
                                                                                )
                                                                            })}
                                                                        </>
                                                                    ) : (
                                                                        <div className="text-muted text-sm">
                                                                            No generation events found in this trace.
                                                                            {fullTrace.events
                                                                                ? ` (Trace has ${fullTrace.events.length} total events)`
                                                                                : ' (No events loaded)'}
                                                                        </div>
                                                                    )
                                                                })()
                                                            ) : (
                                                                <div className="text-muted text-sm">
                                                                    Failed to load trace details
                                                                </div>
                                                            )}
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
