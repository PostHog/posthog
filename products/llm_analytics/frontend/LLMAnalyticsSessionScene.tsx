import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { Suspense, lazy } from 'react'

import { IconWrench } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { LLMTrace } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AIObservabilityRenameBanner } from './AIObservabilityRenameBanner'
import { LLMAnalyticsTraceEvents } from './components/LLMAnalyticsTraceEvents'
import { SentimentBar } from './components/SentimentTag'
import { TranscriptBubbleStream } from './ConversationDisplay/TranscriptBubbleStream'
import { SessionTurn } from './extractSessionTurns'
import { TraceSummary, llmAnalyticsSessionDataLogic } from './llmAnalyticsSessionDataLogic'
import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'
import { llmSentimentLazyLoaderLogic } from './llmSentimentLazyLoaderLogic'
import { SENTIMENT_DATE_WINDOW_DAYS } from './sentimentUtils'
import { formatLLMCost, getTraceTimestamp, sanitizeTraceUrlSearchParams } from './utils'

const LLMASessionFeedbackDisplay = lazy(() =>
    import('./LLMASessionFeedbackDisplay').then((m) => ({ default: m.LLMASessionFeedbackDisplay }))
)

export const scene: SceneExport = {
    component: LLMAnalyticsSessionScene,
    logic: llmAnalyticsSessionLogic,
}

export function LLMAnalyticsSessionScene({ tabId }: { tabId?: string }): JSX.Element {
    const sessionLogic = llmAnalyticsSessionLogic({ tabId })
    const { sessionId, query } = useValues(sessionLogic)
    const sessionDataLogic = llmAnalyticsSessionDataLogic({ sessionId, query, tabId })

    useAttachedLogic(sessionDataLogic, sessionLogic)

    return (
        <BindLogic logic={llmAnalyticsSessionLogic} props={{ tabId }}>
            <BindLogic logic={llmAnalyticsSessionDataLogic} props={{ sessionId, query, tabId }}>
                <SessionSceneWrapper />
            </BindLogic>
        </BindLogic>
    )
}

function SessionTraceSentimentBar({ traceId, createdAt }: { traceId: string; createdAt?: string }): JSX.Element | null {
    const { sentimentByTraceId, isTraceLoading } = useValues(llmSentimentLazyLoaderLogic)
    const { ensureSentimentLoaded } = useActions(llmSentimentLazyLoaderLogic)

    const cached = sentimentByTraceId[traceId]
    const loading = isTraceLoading(traceId)

    if (cached === undefined && !loading) {
        ensureSentimentLoaded(
            traceId,
            createdAt
                ? { dateFrom: createdAt, dateTo: dayjs(createdAt).add(SENTIMENT_DATE_WINDOW_DAYS, 'day').toISOString() }
                : undefined
        )
    }

    if (cached === null) {
        return null
    }

    return (
        <SentimentBar
            label={cached?.label ?? 'neutral'}
            score={cached?.score ?? 0}
            loading={loading || cached === undefined}
            messages={cached?.messages}
        />
    )
}

function SessionSceneWrapper(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showFeedback = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS]
    const showSentiment = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT]

    const { traces, responseLoading, responseError, sessionTurns, hasMoreData, nextDataLoading, summariesLoading } =
        useValues(llmAnalyticsSessionDataLogic)
    const { sessionId } = useValues(llmAnalyticsSessionLogic)
    const { summarizeAllTraces, loadNextData } = useActions(llmAnalyticsSessionDataLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    // Compute the URL search-param passthrough once for the page, not per turn —
    // every `SessionTurnView` consumes the same `traceSearchParams`.
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    const showSessionSummarization =
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSION_SUMMARIZATION] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

    // Calculate session aggregates
    const sessionStats = traces.reduce(
        (acc, trace) => ({
            totalCost: acc.totalCost + (trace.totalCost || 0),
            totalLatency: acc.totalLatency + (trace.totalLatency || 0),
            traceCount: acc.traceCount + 1,
        }),
        { totalCost: 0, totalLatency: 0, traceCount: 0 }
    )

    if (responseLoading) {
        return <SpinnerOverlay />
    }
    if (responseError) {
        return <InsightErrorState />
    }
    if (!traces || traces.length === 0) {
        return <InsightEmptyState heading="No traces found" detail="This session has no traces." />
    }

    return (
        <div className="relative flex flex-col gap-4">
            <SceneBreadcrumbBackButton />
            <AIObservabilityRenameBanner />
            <header className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex gap-1.5 flex-wrap">
                    <LemonTag size="medium" className="bg-surface-primary">
                        <span className="font-mono">{sessionId}</span>
                    </LemonTag>
                    <LemonTag size="medium" className="bg-surface-primary">
                        {sessionStats.traceCount}
                        {hasMoreData ? '+' : ''} {sessionStats.traceCount === 1 ? 'turn' : 'turns'}
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
                    {showFeedback && (
                        <Suspense fallback={<Spinner />}>
                            <LLMASessionFeedbackDisplay sessionId={sessionId} />
                        </Suspense>
                    )}
                </div>
                {showSessionSummarization && (
                    <SummarizeAllButton
                        loading={summariesLoading}
                        dataProcessingAccepted={dataProcessingAccepted}
                        onSummarize={summarizeAllTraces}
                    />
                )}
            </header>

            <div className="flex flex-col">
                {sessionTurns.map((turn) => (
                    <SessionTurnView
                        key={turn.trace.id}
                        turn={turn}
                        showSentiment={showSentiment}
                        showSessionSummarization={!!showSessionSummarization}
                        traceSearchParams={traceSearchParams}
                    />
                ))}
                {hasMoreData && (
                    <div className="flex justify-center pt-4">
                        <LemonButton
                            type="secondary"
                            loading={nextDataLoading}
                            onClick={loadNextData}
                            data-attr="llm-session-load-more-traces"
                        >
                            Load more turns
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}

function SummarizeAllButton({
    loading,
    dataProcessingAccepted,
    onSummarize,
}: {
    loading: boolean
    dataProcessingAccepted: boolean
    onSummarize: () => void
}): JSX.Element {
    if (!dataProcessingAccepted) {
        return (
            <AIConsentPopoverWrapper showArrow onApprove={onSummarize} hidden={loading}>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={loading}
                        disabledReason="AI data processing must be approved to summarize traces"
                        data-attr="llm-session-summarize-all"
                    >
                        Summarize all turns
                    </LemonButton>
                </AccessControlAction>
            </AIConsentPopoverWrapper>
        )
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                size="small"
                onClick={onSummarize}
                loading={loading}
                data-attr="llm-session-summarize-all"
            >
                Summarize all turns
            </LemonButton>
        </AccessControlAction>
    )
}

function SessionTurnView({
    turn,
    showSentiment,
    showSessionSummarization,
    traceSearchParams,
}: {
    turn: SessionTurn
    showSentiment: boolean
    showSessionSummarization: boolean
    traceSearchParams: Record<string, unknown>
}): JSX.Element {
    const { traceSummaries, loadingFullTraces, fullTraces, stepsExpandedTraceIds, expandedGenerationIds } =
        useValues(llmAnalyticsSessionDataLogic)
    const { toggleSteps, toggleGenerationExpanded, loadFullTrace } = useActions(llmAnalyticsSessionDataLogic)

    const trace = turn.trace
    const summary: TraceSummary | undefined = traceSummaries[trace.id]
    const isLoading = loadingFullTraces.has(trace.id)
    const stepsShown = stepsExpandedTraceIds.has(trace.id)
    const fullTrace = fullTraces[trace.id]
    const baseTraceParams = {
        ...traceSearchParams,
        timestamp: getTraceTimestamp(trace.createdAt),
    }
    const traceUrl = combineUrl(urls.llmAnalyticsTrace(trace.id), baseTraceParams).url
    const summaryUrl = combineUrl(urls.llmAnalyticsTrace(trace.id), { ...baseTraceParams, tab: 'summary' }).url

    const canShowSteps = turn.isLoaded && turn.userVisibleTurn

    return (
        <div className="flex flex-col">
            <div className="flex items-center gap-3 py-3 text-xs text-muted">
                <div className="flex-1 border-t" />
                <TZLabel time={trace.createdAt} formatDate="MMM D, YYYY" formatTime="h:mm A" />
                <div className="flex-1 border-t" />
            </div>
            <div className="flex gap-10 pb-4">
                <div className="flex-1 min-w-0 flex flex-col gap-2">
                    {showSessionSummarization && summary && (
                        <TurnSummaryLine summary={summary} summaryUrl={summaryUrl} />
                    )}

                    <TurnBody turn={turn} isLoading={isLoading} onLoad={() => loadFullTrace(trace.id)} />

                    {turn.tools.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap text-xs text-muted">
                            <IconWrench className="text-sm shrink-0" />
                            {turn.tools.map((name) => (
                                <LemonTag key={name} size="small" className="font-mono">
                                    {name}
                                </LemonTag>
                            ))}
                        </div>
                    )}

                    {(trace.errorCount ?? 0) > 0 && (
                        <div className="flex items-center gap-2 min-w-0">
                            <LemonTag type="danger" size="small" className="shrink-0">
                                {trace.errorCount === 1 ? '1 error' : `${trace.errorCount} errors`}
                            </LemonTag>
                            {turn.errors.length > 0 && (
                                <Tooltip
                                    title={
                                        <div className="flex flex-col gap-1">
                                            {turn.errors.map((e, i) => (
                                                <div key={i}>
                                                    <strong>{e.label}:</strong> {e.message}
                                                </div>
                                            ))}
                                        </div>
                                    }
                                >
                                    <span className="text-xs text-muted truncate">
                                        {turn.errors[0].label} · {turn.errors[0].message}
                                        {turn.errors.length > 1 && ` · +${turn.errors.length - 1} more`}
                                    </span>
                                </Tooltip>
                            )}
                        </div>
                    )}

                    {canShowSteps && stepsShown && (
                        <StepsPanel
                            traceId={trace.id}
                            fullTrace={fullTrace}
                            expandedEventIds={expandedGenerationIds}
                            onToggleEventExpand={toggleGenerationExpanded}
                        />
                    )}
                </div>

                <div className="w-40 shrink-0 flex flex-col gap-1 text-xs text-muted">
                    {showSentiment && <SessionTraceSentimentBar traceId={trace.id} createdAt={trace.createdAt} />}
                    <div className="flex flex-col gap-1 items-start">
                        {canShowSteps && (
                            <LemonButton size="xsmall" type="tertiary" onClick={() => toggleSteps(trace.id)}>
                                {stepsShown ? 'Hide steps' : 'Show steps'}
                            </LemonButton>
                        )}
                        <Link to={traceUrl} target="_blank" className="text-xs">
                            Open trace
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}

function TurnSummaryLine({ summary, summaryUrl }: { summary: TraceSummary; summaryUrl: string }): JSX.Element {
    if (summary.loading) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <Spinner className="text-lg" />
                <span>Generating summary...</span>
            </div>
        )
    }
    if (summary.error) {
        return (
            <Tooltip title={summary.error}>
                <span className="text-danger text-sm">Failed to generate summary</span>
            </Tooltip>
        )
    }
    return (
        <Link to={summaryUrl} className="text-sm font-medium">
            {summary.title}
        </Link>
    )
}

function TurnBody({
    turn,
    isLoading,
    onLoad,
}: {
    turn: SessionTurn
    isLoading: boolean
    onLoad: () => void
}): JSX.Element {
    if (isLoading) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm py-2">
                <Spinner className="text-lg" />
                <span>Loading conversation…</span>
            </div>
        )
    }
    if (!turn.isLoaded) {
        return (
            <div className="py-2">
                <LemonButton size="small" type="secondary" onClick={onLoad}>
                    Show conversation
                </LemonButton>
            </div>
        )
    }
    if (!turn.userVisibleTurn) {
        return <div className="text-muted text-sm py-2">No conversational turn to render in this trace.</div>
    }
    // `turn.newInputs` / `outputs` come pre-deduped from `extractSessionTurns`.
    return <TranscriptBubbleStream inputs={turn.newInputs} outputs={turn.outputs} />
}

function StepsPanel({
    traceId,
    fullTrace,
    expandedEventIds,
    onToggleEventExpand,
}: {
    traceId: string
    fullTrace: LLMTrace | undefined
    expandedEventIds: Set<string>
    onToggleEventExpand: (eventId: string) => void
}): JSX.Element {
    return (
        <div className="border rounded bg-bg-light p-3">
            <LLMAnalyticsTraceEvents
                trace={fullTrace}
                isLoading={false}
                expandedEventIds={expandedEventIds}
                onToggleEventExpand={onToggleEventExpand}
                traceId={traceId}
            />
        </div>
    )
}
