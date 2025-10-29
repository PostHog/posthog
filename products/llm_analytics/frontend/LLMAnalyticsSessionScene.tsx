import { BindLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { LLMTrace, NodeKind, TraceQuery } from '~/queries/schema/schema-general'
import { EventDetails } from '~/scenes/activity/explore/EventDetails'
import { EventType } from '~/types'

import { llmAnalyticsSessionDataLogic } from './llmAnalyticsSessionDataLogic'
import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'
import { formatLLMCost } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsSessionScene,
    logic: llmAnalyticsSessionLogic,
}

export function LLMAnalyticsSessionScene(): JSX.Element {
    const { sessionId, query } = useValues(llmAnalyticsSessionLogic)

    return (
        <BindLogic logic={llmAnalyticsSessionDataLogic} props={{ sessionId, query }}>
            <SessionSceneWrapper />
        </BindLogic>
    )
}

function SessionSceneWrapper(): JSX.Element {
    const { traces, responseLoading, responseError } = useValues(llmAnalyticsSessionDataLogic)
    const { sessionId } = useValues(llmAnalyticsSessionLogic)
    const [expandedTraceIds, setExpandedTraceIds] = useState<Set<string>>(new Set())
    const [expandedGenerationIds, setExpandedGenerationIds] = useState<Set<string>>(new Set())
    const [fullTraces, setFullTraces] = useState<Record<string, LLMTrace>>({})
    const [loadingFullTraces, setLoadingFullTraces] = useState<Set<string>>(new Set())

    const handleTraceExpand = async (traceId: string): Promise<void> => {
        const newExpanded = new Set(expandedTraceIds)
        if (newExpanded.has(traceId)) {
            newExpanded.delete(traceId)
            setExpandedTraceIds(newExpanded)
        } else {
            newExpanded.add(traceId)
            setExpandedTraceIds(newExpanded)

            if (!fullTraces[traceId] && !loadingFullTraces.has(traceId)) {
                setLoadingFullTraces(new Set(loadingFullTraces).add(traceId))

                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
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

    const handleGenerationExpand = (generationId: string): void => {
        const newExpanded = new Set(expandedGenerationIds)
        if (newExpanded.has(generationId)) {
            newExpanded.delete(generationId)
        } else {
            newExpanded.add(generationId)
        }
        setExpandedGenerationIds(newExpanded)
    }

    // Calculate session aggregates
    const sessionStats = traces.reduce(
        (acc, trace) => ({
            totalCost: acc.totalCost + (trace.totalCost || 0),
            totalLatency: acc.totalLatency + (trace.totalLatency || 0),
            traceCount: acc.traceCount + 1,
            firstSeen: !acc.firstSeen || trace.createdAt < acc.firstSeen ? trace.createdAt : acc.firstSeen,
            lastSeen: !acc.lastSeen || trace.createdAt > acc.lastSeen ? trace.createdAt : acc.lastSeen,
        }),
        { totalCost: 0, totalLatency: 0, traceCount: 0, firstSeen: '', lastSeen: '' }
    )

    return (
        <>
            {responseLoading ? (
                <SpinnerOverlay />
            ) : responseError ? (
                <InsightErrorState />
            ) : !traces || traces.length === 0 ? (
                <InsightEmptyState heading="No traces found" detail="This session has no traces." />
            ) : (
                <div className="relative flex flex-col gap-3">
                    <SceneBreadcrumbBackButton />
                    <div className="flex items-start justify-between">
                        <header className="flex gap-1.5 flex-wrap">
                            <LemonTag size="medium" className="bg-surface-primary">
                                <span className="font-mono">{sessionId}</span>
                            </LemonTag>
                            <LemonTag size="medium" className="bg-surface-primary">
                                {sessionStats.traceCount} {sessionStats.traceCount === 1 ? 'trace' : 'traces'}
                            </LemonTag>
                            {sessionStats.totalCost > 0 && (
                                <LemonTag size="medium" className="bg-surface-primary">
                                    Total: {formatLLMCost(sessionStats.totalCost)}
                                </LemonTag>
                            )}
                            {sessionStats.totalLatency > 0 && (
                                <LemonTag size="medium" className="bg-surface-primary">
                                    {sessionStats.totalLatency.toFixed(2)}s
                                </LemonTag>
                            )}
                        </header>
                    </div>
                    <div className="bg-surface-primary border rounded p-4">
                        <h3 className="font-semibold text-sm mb-3">Traces in this session</h3>
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
                                                            const allEvents =
                                                                fullTrace.events
                                                                    ?.filter(
                                                                        (e) =>
                                                                            e.event === '$ai_generation' ||
                                                                            e.event === '$ai_span'
                                                                    )
                                                                    .sort(
                                                                        (a, b) =>
                                                                            new Date(a.createdAt).getTime() -
                                                                            new Date(b.createdAt).getTime()
                                                                    ) || []

                                                            return allEvents.length > 0 ? (
                                                                <>
                                                                    {allEvents.map((event) => {
                                                                        const isGeneration =
                                                                            event.event === '$ai_generation'
                                                                        const eventForDetails: EventType = {
                                                                            id: event.id,
                                                                            distinct_id: '',
                                                                            properties: event.properties,
                                                                            event: event.event,
                                                                            timestamp: event.createdAt,
                                                                            elements: [],
                                                                        }
                                                                        const isExpanded = expandedGenerationIds.has(
                                                                            event.id
                                                                        )
                                                                        const latency = event.properties.$ai_latency
                                                                        const hasError =
                                                                            event.properties.$ai_error ||
                                                                            event.properties.$ai_is_error

                                                                        // Generation-specific properties
                                                                        const model =
                                                                            event.properties.$ai_model ||
                                                                            'Unknown model'
                                                                        const cost = event.properties.$ai_total_cost_usd

                                                                        // Span-specific properties
                                                                        const spanName =
                                                                            event.properties.$ai_span_name ||
                                                                            'Unnamed span'

                                                                        return (
                                                                            <div
                                                                                key={event.id}
                                                                                className="border rounded bg-bg-3000"
                                                                            >
                                                                                <div
                                                                                    className="p-2 hover:bg-side-light cursor-pointer flex items-center gap-2"
                                                                                    onClick={() =>
                                                                                        handleGenerationExpand(event.id)
                                                                                    }
                                                                                >
                                                                                    <div className="flex-shrink-0">
                                                                                        {isExpanded ? (
                                                                                            <IconChevronDown className="text-base" />
                                                                                        ) : (
                                                                                            <IconChevronRight className="text-base" />
                                                                                        )}
                                                                                    </div>
                                                                                    <div className="flex-1 flex items-center gap-2 flex-wrap min-w-0">
                                                                                        <LemonTag
                                                                                            type={
                                                                                                isGeneration
                                                                                                    ? 'success'
                                                                                                    : 'default'
                                                                                            }
                                                                                            size="small"
                                                                                            className="uppercase"
                                                                                        >
                                                                                            {isGeneration
                                                                                                ? 'Generation'
                                                                                                : 'Span'}
                                                                                        </LemonTag>
                                                                                        {hasError && (
                                                                                            <LemonTag
                                                                                                type="danger"
                                                                                                size="small"
                                                                                            >
                                                                                                Error
                                                                                            </LemonTag>
                                                                                        )}
                                                                                        <span className="text-xs truncate">
                                                                                            {isGeneration
                                                                                                ? model
                                                                                                : spanName}
                                                                                        </span>
                                                                                        {typeof latency ===
                                                                                            'number' && (
                                                                                            <LemonTag
                                                                                                type="muted"
                                                                                                size="small"
                                                                                            >
                                                                                                {latency.toFixed(2)}s
                                                                                            </LemonTag>
                                                                                        )}
                                                                                        {isGeneration &&
                                                                                            typeof cost ===
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
                                                                                {isExpanded && (
                                                                                    <div className="border-t">
                                                                                        <EventDetails
                                                                                            event={eventForDetails}
                                                                                        />
                                                                                    </div>
                                                                                )}
                                                                            </div>
                                                                        )
                                                                    })}
                                                                </>
                                                            ) : (
                                                                <div className="text-muted text-sm">
                                                                    No generation or span events found in this trace.
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
                </div>
            )}
        </>
    )
}
