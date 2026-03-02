import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React, { useEffect, useState } from 'react'

import {
    IconAIText,
    IconChat,
    IconChevronLeft,
    IconChevronRight,
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

import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { identifierToHuman } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { ClustersTabContent } from './components/ClustersTabContent'
import { EvalsTabContent } from './components/EvalsTabContent'
import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { SentimentBar } from './components/SentimentTag'
import { TraceAggregationInfo } from './components/TraceAggregationInfo'
import { TraceConversationContent } from './components/TraceConversationContent'
import { TraceEventMetadata } from './components/TraceEventMetadata'
import { EventTypeTag, TraceSidebarBase } from './components/TraceSidebarBase'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { SaveToDatasetButton } from './datasets/SaveToDatasetButton'
import { FeedbackViewDisplay } from './feedback-view/FeedbackViewDisplay'
import { useAIData } from './hooks/useAIData'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { DisplayOption, TraceViewMode, llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'
import { llmPersonsLazyLoaderLogic } from './llmPersonsLazyLoaderLogic'
import { llmSentimentLazyLoaderLogic } from './llmSentimentLazyLoaderLogic'
import { llmPlaygroundPromptsLogic } from './playground/llmPlaygroundPromptsLogic'
import { flattenGenerationMessages } from './sentimentUtils'
import { SummaryViewDisplay } from './summary-view/SummaryViewDisplay'
import { TextViewDisplay } from './text-view/TextViewDisplay'
import { buildMinimalTraceJSON, exportTraceToClipboard } from './traceExportUtils'
import { findNodeByEventId, hasTraceContent } from './traceViewUtils'
import { usePosthogAIBillingCalculations } from './usePosthogAIBillingCalculations'
import {
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMUsage,
    getSessionID,
    getSessionStartTimestamp,
    isLLMEvent,
    removeMilliseconds,
    sanitizeTraceUrlSearchParams,
} from './utils'

function TraceNavigation(): JSX.Element {
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { viewMode, newerTraceId, newerTimestamp, olderTraceId, olderTimestamp, neighborsLoading } =
        useValues(traceLogic)
    const { searchParams } = useValues(router)
    const baseSearchParams = sanitizeTraceUrlSearchParams(searchParams)

    // Navigate to newer (more recent) or older traces
    const goToNewer = (): void => {
        if (newerTraceId) {
            router.actions.push(
                combineUrl(urls.llmAnalyticsTrace(newerTraceId), {
                    ...baseSearchParams,
                    timestamp: newerTimestamp ?? undefined,
                    tab: viewMode,
                }).url
            )
        }
    }

    const goToOlder = (): void => {
        if (olderTraceId) {
            router.actions.push(
                combineUrl(urls.llmAnalyticsTrace(olderTraceId), {
                    ...baseSearchParams,
                    timestamp: olderTimestamp ?? undefined,
                    tab: viewMode,
                }).url
            )
        }
    }

    useKeyboardHotkeys(
        {
            p: { action: goToNewer, disabled: !newerTraceId || neighborsLoading },
            n: { action: goToOlder, disabled: !olderTraceId || neighborsLoading },
        },
        [olderTraceId, newerTraceId, olderTimestamp, newerTimestamp, neighborsLoading, viewMode]
    )

    return (
        <div className="flex items-center gap-1">
            <LemonButton
                icon={<IconChevronLeft />}
                size="xsmall"
                type="secondary"
                disabled={!newerTraceId || neighborsLoading}
                onClick={goToNewer}
                tooltip="Newer trace"
                sideIcon={<KeyboardShortcut p />}
            />
            <LemonButton
                icon={<IconChevronRight />}
                size="xsmall"
                type="secondary"
                disabled={!olderTraceId || neighborsLoading}
                onClick={goToOlder}
                tooltip="Older trace"
                sideIcon={<KeyboardShortcut n />}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: LLMAnalyticsTraceScene,
    logic: llmAnalyticsTraceLogic,
}

export function LLMAnalyticsTraceScene({ tabId }: { tabId?: string }): JSX.Element {
    const traceLogic = llmAnalyticsTraceLogic({ tabId })
    const { traceId, query, searchQuery } = useValues(traceLogic)
    const logicProps = { traceId, query, cachedResults: null, searchQuery, tabId }
    const traceDataLogic = llmAnalyticsTraceDataLogic(logicProps)

    useAttachedLogic(traceDataLogic, traceLogic)

    return (
        <BindLogic logic={llmPersonsLazyLoaderLogic} props={{}}>
            <BindLogic logic={llmAnalyticsTraceLogic} props={{ tabId }}>
                <BindLogic logic={llmAnalyticsTraceDataLogic} props={logicProps}>
                    <TraceSceneWrapper />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function TraceSceneWrapper(): JSX.Element {
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const traceDataLogic = useMountedLogic(llmAnalyticsTraceDataLogic)
    const { searchQuery, commentCount } = useValues(traceLogic)
    const { searchParams } = useValues(router)
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
    } = useValues(traceDataLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { showBillingInfo, markupUsd, billedTotalUsd, billedCredits } = usePosthogAIBillingCalculations(enrichedTree)
    const backTo = searchParams.back_to
    const backPath =
        backTo === 'generations'
            ? combineUrl(urls.llmAnalyticsGenerations(), searchParams).url
            : combineUrl(urls.llmAnalyticsTraces(), searchParams).url

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
                    <div className="flex flex-col gap-1">
                        <SceneTitleSection
                            name={trace.id}
                            resourceType={{ type: 'llm_analytics' }}
                            forceBackTo={{
                                name: backTo === 'generations' ? 'Generations' : 'Traces',
                                path: backPath,
                                key: backTo === 'generations' ? 'generations' : 'traces',
                            }}
                            actions={
                                featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRACE_NAVIGATION] ? (
                                    <TraceNavigation />
                                ) : undefined
                            }
                            noBorder
                        />
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
                                <ShareTraceButton trace={trace} />
                            </div>
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
    const { personsCache } = useValues(llmPersonsLazyLoaderLogic)
    const { getTraceSentiment, isTraceLoading } = useValues(llmSentimentLazyLoaderLogic)
    const { ensureSentimentLoaded } = useActions(llmSentimentLazyLoaderLogic)

    const showSentiment = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT]
    const sentimentResult = showSentiment ? getTraceSentiment(trace.id) : undefined
    const sentimentLoading = showSentiment ? isTraceLoading(trace.id) : false
    if (showSentiment && sentimentResult === undefined && !sentimentLoading) {
        ensureSentimentLoaded(trace.id)
    }

    const cached = personsCache[trace.distinctId]

    const personData = cached
        ? { distinct_id: cached.distinct_id, properties: cached.properties }
        : { distinct_id: trace.distinctId }

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
            <Chip title="Person">
                <PersonDisplay withIcon="sm" person={personData} />
            </Chip>
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
            {sentimentResult && !sentimentLoading && (
                <Chip title="Sentiment">
                    <SentimentBar
                        label={sentimentResult.label ?? 'neutral'}
                        score={sentimentResult.score ?? 0}
                        messages={flattenGenerationMessages(sentimentResult.generations)}
                    />
                </Chip>
            )}
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
        const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
        const { setupPlaygroundFromEvent } = useActions(llmPlaygroundPromptsLogic)
        const { featureFlags } = useValues(featureFlagLogic)
        const { displayOption, lineNumber, initialTab, viewMode } = useValues(traceLogic)
        const { handleTextViewFallback, copyLinePermalink, setViewMode } = useActions(traceLogic)

        const node = event && isLLMEvent(event) ? findNodeByEventId(tree, event.id) : null
        const aggregation = node?.aggregation || null

        const childEventsForSessionId: LLMTraceEvent[] | undefined = node?.children?.map((child) => child.event)
        const sessionId = event ? getSessionID(event, childEventsForSessionId) : null
        const hasSessionRecording = !!sessionId

        const isGenerationEvent = event && isLLMEvent(event) && event.event === '$ai_generation'

        const promptName = event && isLLMEvent(event) ? event.properties['$ai_prompt_name'] : null
        const showPromptButton = !!promptName

        const showPlaygroundButton = isGenerationEvent

        const showSaveToDatasetButton = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]

        const showEvalsTab = isGenerationEvent && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]

        const showSummaryTab =
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SUMMARIZATION] ||
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

        const showClustersTab =
            !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERS_TAB] ||
            !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

        const showFeedbackTab = true

        const isTopLevelTraceWithoutContent = !event || (!isLLMEvent(event) && !hasTraceContent(event))

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
                            <TraceEventMetadata event={event} showStreamingMetadata />
                            {isLLMEvent(event) && <ParametersHeader eventProperties={event.properties} />}
                            {aggregation && <TraceAggregationInfo aggregation={aggregation} />}
                            {(showPromptButton ||
                                showPlaygroundButton ||
                                hasSessionRecording ||
                                showSaveToDatasetButton) && (
                                <div className="flex flex-row items-center gap-2">
                                    {showPromptButton && (
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            icon={<IconAIText />}
                                            to={urls.llmAnalyticsPrompt(promptName)}
                                            tooltip="View the prompt used for this generation"
                                            data-attr="view-prompt-trace"
                                        >
                                            View prompt
                                        </LemonButton>
                                    )}
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
                                                <NoTopLevelTraceEmptyState />
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
                                                <TraceConversationContent
                                                    event={event}
                                                    traceId={trace.id}
                                                    searchQuery={searchQuery}
                                                    displayOption={displayOption}
                                                    traceMetricsSlot={<TraceMetricsTable />}
                                                />
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
                                              label: 'Summary',
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
                                                      distinctId={trace.distinctId}
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
                                ...(showFeedbackTab
                                    ? [
                                          {
                                              key: TraceViewMode.Feedback,
                                              label: (
                                                  <>
                                                      Feedback{' '}
                                                      <LemonTag className="ml-1" type="completion">
                                                          Beta
                                                      </LemonTag>
                                                  </>
                                              ),
                                              content: <FeedbackViewDisplay />,
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
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const traceDataLogic = useMountedLogic(llmAnalyticsTraceDataLogic)
    const { availableEventTypes } = useValues(traceDataLogic)
    const { eventTypeExpanded } = useValues(traceLogic)
    const { toggleEventTypeExpanded } = useActions(traceLogic)

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

function ShareTraceButton({ trace }: { trace: LLMTrace }): JSX.Element {
    const [visible, setVisible] = useState(false)

    const currentUrl = window.location.href
    const previewUrl = `${window.location.origin}${urls.llmAnalyticsTracePreview()}`

    const handleCopyInternalLink = async (): Promise<void> => {
        await copyToClipboard(currentUrl, 'trace link')
    }

    const handleCopyPreviewLink = async (): Promise<void> => {
        await copyToClipboard(previewUrl, 'trace preview link')
    }

    const handleCopyTraceJson = async (): Promise<void> => {
        await exportTraceToClipboard(trace)
    }

    const handleDownloadTraceJson = (): void => {
        const exportData = buildMinimalTraceJSON(trace)
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
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { displayOption } = useValues(traceLogic)
    const { setDisplayOption } = useActions(traceLogic)
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
    const traceDataLogic = useMountedLogic(llmAnalyticsTraceDataLogic)
    const { metricsAndFeedbackEvents } = useValues(traceDataLogic)

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
