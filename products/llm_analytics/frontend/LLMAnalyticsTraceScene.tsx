import { BindLogic, useActions, useValues } from 'kea'
import React, { useEffect, useState } from 'react'

import {
    IconAIText,
    IconChat,
    IconComment,
    IconCopy,
    IconDownload,
    IconMessage,
    IconReceipt,
    IconShare,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonSelect,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
    Popover,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman, isObject } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { LLMInputOutput } from './LLMInputOutput'
import { ClustersTabContent } from './components/ClustersTabContent'
import { EvalsTabContent } from './components/EvalsTabContent'
import { EventContentDisplayAsync, EventContentGeneration } from './components/EventContentWithAsyncData'
import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { EventTypeTag, TraceSidebarBase } from './components/TraceSidebarBase'
import { SaveToDatasetButton } from './datasets/SaveToDatasetButton'
import { useAIData } from './hooks/useAIData'
import { llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { DisplayOption, TraceViewMode, llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'
import { SummaryViewDisplay } from './summary-view/SummaryViewDisplay'
import { TextViewDisplay } from './text-view/TextViewDisplay'
import { buildMinimalTraceJSON, exportTraceToClipboard } from './traceExportUtils'
import { usePosthogAIBillingCalculations } from './usePosthogAIBillingCalculations'
import {
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMLatency,
    formatLLMUsage,
    getSessionID,
    getSessionStartTimestamp,
    isLLMEvent,
    isTraceLevel,
    removeMilliseconds,
} from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsTraceScene,
    logic: llmAnalyticsTraceLogic,
}

export function LLMAnalyticsTraceScene(): JSX.Element {
    const { traceId, query } = useValues(llmAnalyticsTraceLogic)

    return (
        <BindLogic logic={llmAnalyticsTraceDataLogic} props={{ traceId, query, cachedResults: null }}>
            <TraceSceneWrapper />
        </BindLogic>
    )
}

function TraceSceneWrapper(): JSX.Element {
    const { searchQuery, commentCount } = useValues(llmAnalyticsTraceLogic)
    const {
        enrichedTree,
        trace,
        event,
        responseLoading,
        responseError,
        feedbackEvents,
        metricEvents,
        eventMetadata,
        effectiveEventId,
    } = useValues(llmAnalyticsTraceDataLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { showBillingInfo, markupUsd, billedTotalUsd, billedCredits } = usePosthogAIBillingCalculations(enrichedTree)

    return (
        <>
            {responseLoading ? (
                <SpinnerOverlay />
            ) : responseError ? (
                <InsightErrorState />
            ) : !trace ? (
                <NotFound object="trace" />
            ) : (
                <div className="relative flex flex-col gap-3">
                    <SceneBreadcrumbBackButton />
                    <div className="flex items-start justify-between">
                        <TraceMetadata
                            trace={trace}
                            metricEvents={metricEvents as LLMTraceEvent[]}
                            feedbackEvents={feedbackEvents as LLMTraceEvent[]}
                            billedTotalUsd={billedTotalUsd}
                            billedCredits={billedCredits}
                            markupUsd={markupUsd}
                            showBillingInfo={showBillingInfo}
                        />
                        <div className="flex flex-wrap justify-end items-center gap-x-2 gap-y-1">
                            <DisplayOptionsSelect />
                            {(featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS] ||
                                featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]) && (
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    icon={
                                        <IconWithCount count={commentCount} showZero={false}>
                                            <IconComment />
                                        </IconWithCount>
                                    }
                                    onClick={() => openSidePanel(SidePanelTab.Discussion)}
                                    tooltip="Add comments on this trace"
                                    data-attr="open-trace-discussion"
                                >
                                    Discussion
                                </LemonButton>
                            )}
                            <ShareTraceButton trace={trace} tree={enrichedTree} />
                        </div>
                    </div>
                    <div className="flex flex-1 min-h-0 gap-3 flex-col md:flex-row">
                        <TraceSidebar
                            trace={trace}
                            eventId={effectiveEventId}
                            tree={enrichedTree}
                            showBillingInfo={showBillingInfo}
                        />
                        <EventContent
                            trace={trace}
                            event={event}
                            tree={enrichedTree}
                            searchQuery={searchQuery}
                            eventMetadata={eventMetadata}
                            showBillingInfo={showBillingInfo}
                        />
                    </div>
                </div>
            )}
        </>
    )
}

function Chip({
    title,
    children,
    icon,
}: {
    title: string
    children: React.ReactNode
    icon?: JSX.Element
}): JSX.Element {
    return (
        <Tooltip title={title}>
            <LemonTag size="medium" className="bg-surface-primary" icon={icon}>
                <span className="sr-only">{title}</span>
                {children}
            </LemonTag>
        </Tooltip>
    )
}

function UsageChip({ event }: { event: LLMTraceEvent | LLMTrace }): JSX.Element | null {
    const usage = formatLLMUsage(event)
    return usage ? (
        <Chip title="Usage" icon={<IconAIText />}>
            {usage}
        </Chip>
    ) : null
}

function TraceMetadata({
    trace,
    metricEvents,
    feedbackEvents,
    billedTotalUsd,
    billedCredits,
    markupUsd,
    showBillingInfo,
}: {
    trace: LLMTrace
    metricEvents: LLMTraceEvent[]
    feedbackEvents: LLMTraceEvent[]
    billedTotalUsd?: number
    billedCredits?: number
    markupUsd?: number
    showBillingInfo?: boolean
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const getSessionUrl = (sessionId: string): string => {
        if (
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW] ||
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
        ) {
            return urls.llmAnalyticsSession(sessionId, { timestamp: getSessionStartTimestamp(trace.createdAt) })
        }
        // Fallback to filtering traces by session when feature flag is off
        const filter = [
            {
                key: '$ai_session_id',
                value: [sessionId],
                operator: 'exact',
                type: 'event',
            },
        ]
        const params = new URLSearchParams()
        params.set('filters', JSON.stringify(filter))
        return `${urls.llmAnalyticsTraces()}?${params.toString()}`
    }

    return (
        <header className="flex gap-1.5 flex-wrap">
            {'person' in trace && (
                <Chip title="Person">
                    <PersonDisplay withIcon="sm" person={trace.person} />
                </Chip>
            )}
            {trace.aiSessionId && (
                <Chip
                    title={
                        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW] ||
                        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
                            ? 'AI Session ID - Click to view session details'
                            : 'AI Session ID - Click to filter traces by this session'
                    }
                >
                    <Link to={getSessionUrl(trace.aiSessionId)} subtle>
                        <span className="font-mono">{trace.aiSessionId.slice(0, 8)}...</span>
                    </Link>
                </Chip>
            )}
            <UsageChip event={trace} />
            {typeof trace.inputCost === 'number' && (
                <Chip title="Input cost" icon={<IconArrowUp />}>
                    {formatLLMCost(trace.inputCost)}
                </Chip>
            )}
            {typeof trace.outputCost === 'number' && (
                <Chip title="Output cost" icon={<IconArrowDown />}>
                    {formatLLMCost(trace.outputCost)}
                </Chip>
            )}
            {typeof trace.totalCost === 'number' && (
                <Chip title="Total cost" icon={<IconReceipt />}>
                    {formatLLMCost(trace.totalCost)}
                </Chip>
            )}
            {showBillingInfo && typeof billedTotalUsd === 'number' && billedTotalUsd > 0 && (
                <Chip title="Billed total" icon={<span className="text-base">💰</span>}>
                    billed: {formatLLMCost(billedTotalUsd)}
                </Chip>
            )}
            {showBillingInfo && typeof markupUsd === 'number' && markupUsd > 0 && (
                <Chip title="Markup (20%)" icon={<span className="text-base">➕</span>}>
                    markup: {formatLLMCost(markupUsd)}
                </Chip>
            )}
            {showBillingInfo && typeof billedTotalUsd === 'number' && billedTotalUsd > 0 && (
                <Chip title="Credits spent" icon={<span className="text-base">💳</span>}>
                    credits: {billedCredits}
                </Chip>
            )}
            {metricEvents.map((metric) => (
                <MetricTag key={metric.id} properties={metric.properties} />
            ))}
            {feedbackEvents.map((feedback) => (
                <FeedbackTag key={feedback.id} properties={feedback.properties} />
            ))}
        </header>
    )
}

function TraceSidebar({
    trace,
    eventId,
    tree,
    showBillingInfo,
}: {
    trace: LLMTrace
    eventId?: string | null
    tree: EnrichedTraceTreeNode[]
    showBillingInfo?: boolean
}): JSX.Element {
    const { mostRelevantEvent, searchOccurrences } = useValues(llmAnalyticsTraceDataLogic)
    const { searchQuery, eventTypeExpanded } = useValues(llmAnalyticsTraceLogic)
    const { setSearchQuery, setEventId } = useActions(llmAnalyticsTraceLogic)

    useEffect(() => {
        if (mostRelevantEvent && searchQuery.trim()) {
            setEventId(mostRelevantEvent.id)
        }
    }, [mostRelevantEvent, searchQuery, setEventId])

    return (
        <TraceSidebarBase
            trace={trace}
            tree={tree}
            selectedEventId={eventId}
            searchQuery={searchQuery}
            searchOccurrencesCount={searchOccurrences.length}
            onSearchChange={setSearchQuery}
            onSelectEvent={setEventId}
            eventTypeExpanded={eventTypeExpanded}
            showBillingInfo={showBillingInfo}
            eventTypeFiltersSlot={<EventTypeFilters />}
        />
    )
}

function EventContentDisplay({
    input,
    output,
    raisedError,
}: {
    input: unknown
    output: unknown
    raisedError?: boolean
}): JSX.Element {
    const { searchQuery } = useValues(llmAnalyticsTraceLogic)
    if (!input && !output) {
        // If we have no data here we should not render anything
        // In future plan to point docs to show how to add custom trace events
        return <></>
    }
    return (
        <LLMInputOutput
            inputDisplay={
                <div className="p-2 text-xs border rounded bg-[var(--color-bg-fill-secondary)]">
                    {isObject(input) ? (
                        <HighlightedJSONViewer src={input} collapsed={4} searchQuery={searchQuery} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(input ?? null)}</span>
                    )}
                </div>
            }
            outputDisplay={
                <div
                    className={cn(
                        'p-2 text-xs border rounded',
                        !raisedError
                            ? 'bg-[var(--color-bg-fill-success-tertiary)]'
                            : 'bg-[var(--color-bg-fill-error-tertiary)]'
                    )}
                >
                    {isObject(output) ? (
                        <HighlightedJSONViewer src={output} collapsed={4} searchQuery={searchQuery} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(output ?? null)}</span>
                    )}
                </div>
            }
        />
    )
}

function findNodeForEvent(tree: EnrichedTraceTreeNode[], eventId: string): EnrichedTraceTreeNode | null {
    for (const node of tree) {
        if (node.event.id === eventId) {
            return node
        }
        if (node.children) {
            const result = findNodeForEvent(node.children, eventId)
            if (result) {
                return result
            }
        }
    }
    return null
}

const EventContent = React.memo(
    ({
        trace,
        event,
        eventMetadata,
        tree,
        searchQuery,
        showBillingInfo,
    }: {
        trace: LLMTrace
        event: LLMTrace | LLMTraceEvent | null
        tree: EnrichedTraceTreeNode[]
        searchQuery?: string
        eventMetadata?: Record<string, unknown>
        showBillingInfo?: boolean
    }): JSX.Element => {
        const { setupPlaygroundFromEvent } = useActions(llmAnalyticsPlaygroundLogic)
        const { featureFlags } = useValues(featureFlagLogic)
        const { displayOption, lineNumber, initialTab, viewMode } = useValues(llmAnalyticsTraceLogic)
        const { handleTextViewFallback, copyLinePermalink, setViewMode } = useActions(llmAnalyticsTraceLogic)

        const node = event && isLLMEvent(event) ? findNodeForEvent(tree, event.id) : null
        const aggregation = node?.aggregation || null

        const childEventsForSessionId: LLMTraceEvent[] | undefined = node?.children?.map((child) => child.event)
        const sessionId = event ? getSessionID(event, childEventsForSessionId) : null
        const hasSessionRecording = !!sessionId

        const isGenerationEvent = event && isLLMEvent(event) && event.event === '$ai_generation'

        const showPlaygroundButton = isGenerationEvent

        const showSaveToDatasetButton = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]

        const showEvalsTab = isGenerationEvent && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]

        const showSummaryTab =
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SUMMARIZATION] ||
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

        const showClustersTab = !!event && isTraceLevel(event) && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERS_TAB]

        // Check if we're viewing a trace with actual content vs. a pseudo-trace (grouping of generations w/o input/output state)
        const isTopLevelTraceWithoutContent = !event || (!isLLMEvent(event) && !event.inputState && !event.outputState)

        // Only pre-load for generation events ($ai_input/$ai_output_choices).
        // TODO: Figure out why spans can't load properties async
        const eventData = isGenerationEvent
            ? {
                  uuid: event.id,
                  input: event.properties.$ai_input,
                  output: event.properties.$ai_output_choices,
              }
            : undefined
        const { input: loadedInput, output: loadedOutput } = useAIData(eventData)

        const handleTryInPlayground = (): void => {
            if (!event || !isLLMEvent(event)) {
                return
            }

            const model = event.properties.$ai_model
            const tools = event.properties.$ai_tools

            setupPlaygroundFromEvent({ model, input: loadedInput, tools })
        }

        return (
            <div className="flex-1 bg-surface-primary max-h-fit border rounded flex flex-col border-primary p-4 overflow-y-auto">
                {!event ? (
                    <InsightEmptyState heading="Event not found" detail="Check if the event ID is correct." />
                ) : (
                    <>
                        <header className="deprecated-space-y-2">
                            <div className="flex-row flex items-center gap-2">
                                <EventTypeTag event={event} />
                                {showBillingInfo &&
                                    isLLMEvent(event) &&
                                    event.event === '$ai_generation' &&
                                    !!event.properties.$ai_billable && (
                                        <span title="Billable" aria-label="Billable" className="text-base">
                                            💰
                                        </span>
                                    )}
                                <h3 className="text-lg font-semibold p-0 m-0 truncate flex-1">
                                    {formatLLMEventTitle(event)}
                                </h3>
                            </div>
                            {isLLMEvent(event) ? (
                                <MetadataHeader
                                    isError={event.properties.$ai_is_error}
                                    inputTokens={event.properties.$ai_input_tokens}
                                    outputTokens={event.properties.$ai_output_tokens}
                                    cacheReadTokens={event.properties.$ai_cache_read_input_tokens}
                                    cacheWriteTokens={event.properties.$ai_cache_creation_input_tokens}
                                    totalCostUsd={event.properties.$ai_total_cost_usd}
                                    model={event.properties.$ai_model}
                                    latency={event.properties.$ai_latency}
                                    timestamp={event.createdAt}
                                />
                            ) : (
                                <MetadataHeader
                                    inputTokens={event.inputTokens}
                                    outputTokens={event.outputTokens}
                                    totalCostUsd={event.totalCost}
                                    latency={event.totalLatency}
                                    timestamp={event.createdAt}
                                />
                            )}
                            {isLLMEvent(event) && <ParametersHeader eventProperties={event.properties} />}
                            {aggregation && (
                                <div className="flex flex-row flex-wrap items-center gap-2">
                                    {aggregation.totalCost > 0 && (
                                        <LemonTag type="muted" size="small">
                                            Total Cost: {formatLLMCost(aggregation.totalCost)}
                                        </LemonTag>
                                    )}
                                    {aggregation.totalLatency > 0 && (
                                        <LemonTag type="muted" size="small">
                                            Total Latency: {formatLLMLatency(aggregation.totalLatency)}
                                        </LemonTag>
                                    )}
                                    {(aggregation.inputTokens > 0 || aggregation.outputTokens > 0) && (
                                        <LemonTag type="muted" size="small">
                                            Tokens: {aggregation.inputTokens} → {aggregation.outputTokens} (∑{' '}
                                            {aggregation.inputTokens + aggregation.outputTokens})
                                        </LemonTag>
                                    )}
                                </div>
                            )}
                            {(showPlaygroundButton || hasSessionRecording || showSaveToDatasetButton) && (
                                <div className="flex flex-row items-center gap-2">
                                    {showPlaygroundButton && (
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            icon={<IconChat />}
                                            onClick={handleTryInPlayground}
                                            tooltip="Try this prompt in the playground"
                                            data-attr="try-in-playground-trace"
                                        >
                                            Try in Playground
                                        </LemonButton>
                                    )}
                                    {showSaveToDatasetButton && (
                                        <SaveToDatasetButton
                                            traceId={trace.id}
                                            timestamp={trace.createdAt}
                                            sourceId={event.id}
                                            input={isLLMEvent(event) ? loadedInput : event.inputState}
                                            output={isLLMEvent(event) ? loadedOutput : event.outputState}
                                            metadata={eventMetadata}
                                        />
                                    )}
                                    {hasSessionRecording && (
                                        <ViewRecordingButton
                                            openPlayerIn={RecordingPlayerType.Modal}
                                            type="secondary"
                                            size="xsmall"
                                            data-attr="llm-analytics"
                                            sessionId={sessionId || undefined}
                                            timestamp={removeMilliseconds(event.createdAt)}
                                        />
                                    )}
                                </div>
                            )}
                        </header>
                        <LemonTabs
                            activeKey={viewMode}
                            onChange={setViewMode}
                            tabs={[
                                {
                                    key: TraceViewMode.Conversation,
                                    label: 'Conversation',
                                    'data-attr': 'llma-trace-conversation-tab',
                                    content: (
                                        <>
                                            {isTopLevelTraceWithoutContent ? (
                                                <InsightEmptyState
                                                    heading="No top-level trace event"
                                                    detail={
                                                        <>
                                                            This trace doesn't have an associated <code>$ai_trace</code>{' '}
                                                            event.
                                                            <br />
                                                            Click on individual generations in the tree to view their
                                                            content.
                                                        </>
                                                    }
                                                />
                                            ) : displayOption === DisplayOption.TextView &&
                                              (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TEXT_VIEW] ||
                                                  featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]) ? (
                                                isLLMEvent(event) &&
                                                (event.event === '$ai_generation' ||
                                                    event.event === '$ai_span' ||
                                                    event.event === '$ai_embedding') ? (
                                                    <TextViewDisplay
                                                        event={event}
                                                        trace={trace}
                                                        lineNumber={lineNumber}
                                                        onFallback={handleTextViewFallback}
                                                        onCopyPermalink={copyLinePermalink}
                                                    />
                                                ) : !isLLMEvent(event) ? (
                                                    <TextViewDisplay
                                                        trace={event}
                                                        tree={tree}
                                                        lineNumber={lineNumber}
                                                        onFallback={handleTextViewFallback}
                                                        onCopyPermalink={copyLinePermalink}
                                                    />
                                                ) : null
                                            ) : (
                                                <>
                                                    {isLLMEvent(event) ? (
                                                        event.event === '$ai_generation' ? (
                                                            <EventContentGeneration
                                                                eventId={event.id}
                                                                rawInput={event.properties.$ai_input}
                                                                rawOutput={
                                                                    event.properties.$ai_output_choices ??
                                                                    event.properties.$ai_output
                                                                }
                                                                tools={event.properties.$ai_tools}
                                                                errorData={event.properties.$ai_error}
                                                                httpStatus={event.properties.$ai_http_status}
                                                                raisedError={event.properties.$ai_is_error}
                                                                searchQuery={searchQuery}
                                                            />
                                                        ) : event.event === '$ai_embedding' ? (
                                                            <EventContentDisplayAsync
                                                                eventId={event.id}
                                                                rawInput={event.properties.$ai_input}
                                                                rawOutput="Embedding vector generated"
                                                            />
                                                        ) : (
                                                            <EventContentDisplayAsync
                                                                eventId={event.id}
                                                                rawInput={event.properties.$ai_input_state}
                                                                rawOutput={
                                                                    event.properties.$ai_output_state ??
                                                                    event.properties.$ai_error
                                                                }
                                                                raisedError={event.properties.$ai_is_error}
                                                            />
                                                        )
                                                    ) : (
                                                        <>
                                                            <TraceMetricsTable />
                                                            <EventContentDisplay
                                                                input={event.inputState}
                                                                output={event.outputState}
                                                            />
                                                        </>
                                                    )}
                                                </>
                                            )}
                                        </>
                                    ),
                                },
                                {
                                    key: TraceViewMode.Raw,
                                    label: 'Raw',
                                    'data-attr': 'llma-trace-raw-tab',
                                    content: (
                                        <div className="p-2">
                                            <JSONViewer src={event} collapsed={2} />
                                        </div>
                                    ),
                                },
                                ...(showSummaryTab
                                    ? [
                                          {
                                              key: TraceViewMode.Summary,
                                              label: (
                                                  <>
                                                      Summary{' '}
                                                      <LemonTag className="ml-1" type="completion">
                                                          Alpha
                                                      </LemonTag>
                                                  </>
                                              ),
                                              'data-attr': 'llma-trace-summary-tab',
                                              content: (
                                                  <SummaryViewDisplay
                                                      trace={!isLLMEvent(event) ? event : undefined}
                                                      event={isLLMEvent(event) ? event : undefined}
                                                      tree={tree}
                                                      autoGenerate={initialTab === 'summary'}
                                                  />
                                              ),
                                          },
                                      ]
                                    : []),
                                ...(showEvalsTab
                                    ? [
                                          {
                                              key: TraceViewMode.Evals,
                                              label: 'Evaluations',
                                              'data-attr': 'llma-trace-evals-tab',
                                              content: (
                                                  <EvalsTabContent
                                                      generationEventId={event.id}
                                                      timestamp={event.createdAt}
                                                      event={event.event}
                                                      distinctId={trace.person.distinct_id}
                                                  />
                                              ),
                                          },
                                      ]
                                    : []),
                                ...(showClustersTab
                                    ? [
                                          {
                                              key: TraceViewMode.Clusters,
                                              label: (
                                                  <>
                                                      Clusters{' '}
                                                      <LemonTag className="ml-1" type="completion">
                                                          Alpha
                                                      </LemonTag>
                                                  </>
                                              ),
                                              content: <ClustersTabContent />,
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </>
                )}
            </div>
        )
    }
)
EventContent.displayName = 'EventContent'

function EventTypeFilters(): JSX.Element {
    const { availableEventTypes } = useValues(llmAnalyticsTraceDataLogic)
    const { eventTypeExpanded } = useValues(llmAnalyticsTraceLogic)
    const { toggleEventTypeExpanded } = useActions(llmAnalyticsTraceLogic)

    if (availableEventTypes.length === 0) {
        return <></>
    }

    return (
        <fieldset className="border border-border rounded p-1.5">
            <legend className="text-xs font-medium text-muted px-1">Expand</legend>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
                {availableEventTypes.map((eventType: string) => (
                    <LemonCheckbox
                        key={eventType}
                        checked={eventTypeExpanded(eventType)}
                        onChange={() => toggleEventTypeExpanded(eventType)}
                        label={<span className="capitalize text-xs">{eventType}s</span>}
                        size="small"
                    />
                ))}
            </div>
        </fieldset>
    )
}

function ShareTraceButton({ trace, tree }: { trace: LLMTrace; tree: EnrichedTraceTreeNode[] }): JSX.Element {
    const [visible, setVisible] = useState(false)

    const currentUrl = window.location.href
    const previewUrl = `${window.location.origin}/llm-analytics/trace-preview`

    const handleCopyInternalLink = async (): Promise<void> => {
        await copyToClipboard(currentUrl, 'trace link')
    }

    const handleCopyPreviewLink = async (): Promise<void> => {
        await copyToClipboard(previewUrl, 'trace preview link')
    }

    const handleCopyTraceJson = async (): Promise<void> => {
        await exportTraceToClipboard(trace, tree)
    }

    const handleDownloadTraceJson = (): void => {
        const exportData = buildMinimalTraceJSON(trace, tree)
        const jsonString = JSON.stringify(exportData, null, 2)
        const blob = new Blob([jsonString], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `trace-${trace.id}.json`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(url)
    }

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="p-3 min-w-72 max-w-96">
                    <div className="flex items-center justify-between mb-3">
                        <span className="font-semibold text-sm">Share trace</span>
                        <LemonButton
                            size="xsmall"
                            onClick={() => setVisible(false)}
                            noPadding
                            data-attr="share-trace-close"
                        >
                            <span className="text-lg leading-none">&times;</span>
                        </LemonButton>
                    </div>

                    <div className="mb-3">
                        <div className="font-medium text-xs mb-1">Share with team members</div>
                        <p className="text-muted text-xs mb-2">
                            Team members with project access can view this trace directly.
                        </p>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconCopy />}
                            onClick={handleCopyInternalLink}
                            fullWidth
                            data-attr="share-trace-copy-link"
                        >
                            Copy link
                        </LemonButton>
                    </div>

                    <LemonDivider className="my-3" />

                    <div>
                        <div className="font-medium text-xs mb-1">Share externally</div>
                        <p className="text-muted text-xs mb-2">
                            Share with people outside your organization using the trace preview.
                        </p>
                        <div className="flex flex-col gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconCopy />}
                                onClick={handleCopyPreviewLink}
                                fullWidth
                                data-attr="share-trace-copy-preview-link"
                            >
                                Copy preview link
                            </LemonButton>
                            <div className="flex gap-2">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconCopy />}
                                    onClick={handleCopyTraceJson}
                                    className="flex-1"
                                    data-attr="share-trace-copy-json"
                                >
                                    Copy trace JSON
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconDownload />}
                                    onClick={handleDownloadTraceJson}
                                    className="flex-1"
                                    data-attr="share-trace-download-json"
                                >
                                    Download JSON
                                </LemonButton>
                            </div>
                        </div>
                        <p className="text-muted text-xs mt-2">
                            Send both the preview link and the trace JSON to the recipient. They'll paste the JSON at
                            the preview link to view the trace.
                        </p>
                    </div>
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconShare />}
                onClick={() => setVisible(!visible)}
                data-attr="share-trace-button"
            >
                Share
            </LemonButton>
        </Popover>
    )
}

function DisplayOptionsSelect(): JSX.Element {
    const { displayOption } = useValues(llmAnalyticsTraceLogic)
    const { setDisplayOption } = useActions(llmAnalyticsTraceLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const displayOptions = [
        {
            value: DisplayOption.ExpandAll,
            label: 'Expand all',
            tooltip: 'Show all messages and full conversation history',
            'data-attr': 'llma-trace-display-expand-all',
        },
        {
            value: DisplayOption.CollapseExceptOutputAndLastInput,
            label: 'Collapse except output and last input',
            tooltip: 'Focus on the most recent input and final output',
            'data-attr': 'llma-trace-display-expand-last',
        },
        ...(featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TEXT_VIEW] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
            ? [
                  {
                      value: DisplayOption.TextView,
                      label: 'Text view',
                      tooltip: 'Simple human readable text view, for humans',
                      'data-attr': 'llma-trace-display-text-view',
                  },
              ]
            : []),
    ]

    return (
        <LemonSelect
            size="xsmall"
            value={displayOption}
            onChange={setDisplayOption}
            options={displayOptions}
            tooltip="Configure how generation conversation messages are displayed"
        />
    )
}

function TraceMetricsTable(): JSX.Element | null {
    const { metricsAndFeedbackEvents } = useValues(llmAnalyticsTraceDataLogic)

    if (!metricsAndFeedbackEvents?.length) {
        return null
    }

    return (
        <div className="mb-3">
            <h4 className="flex items-center gap-x-1.5 text-xs font-semibold mb-2">
                <IconMessage className="text-base" />
                Metrics and user feedback
            </h4>
            <LemonTable
                columns={[
                    {
                        title: 'Metric',
                        key: 'metric',
                        render: (_, { metric }) => <span>{identifierToHuman(metric)}</span>,
                        width: '40%',
                    },
                    {
                        title: 'Value',
                        key: 'value',
                        render: (_, { value }) => <span>{value ?? '–'}</span>,
                        width: '60%',
                    },
                ]}
                dataSource={metricsAndFeedbackEvents}
            />
        </div>
    )
}
