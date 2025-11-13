import { BindLogic, useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { LLMAnalyticsTraceEvents } from './components/LLMAnalyticsTraceEvents'
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
    const {
        traces,
        responseLoading,
        responseError,
        expandedTraceIds,
        expandedGenerationIds,
        fullTraces,
        loadingFullTraces,
    } = useValues(llmAnalyticsSessionDataLogic)
    const { sessionId } = useValues(llmAnalyticsSessionLogic)
    const { toggleTraceExpanded, toggleGenerationExpanded } = useActions(llmAnalyticsSessionDataLogic)

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
                                            onClick={() => toggleTraceExpanded(trace.id)}
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
                                                    {(trace.errorCount ?? 0) > 0 && (
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
                                                        onToggleEventExpand={toggleGenerationExpanded}
                                                    />
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
