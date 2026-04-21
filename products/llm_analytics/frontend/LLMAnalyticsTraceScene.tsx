import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React, { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import {
    IconAIText,
    IconChevronLeft,
    IconChevronRight,
    IconComment,
    IconCopy,
    IconMessage,
    IconPlay,
    IconReceipt,
    IconSearch,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTabs,
    LemonTag,
    LemonTagProps,
    Link,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { identifierToHuman, isObject, pluralize } from 'lib/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, SidePanelTab } from '~/types'

import { ClustersTabContent } from './components/ClustersTabContent'
import { CostBreakdownTooltip } from './components/CostBreakdownTooltip'
import { EvalResultBadges } from './components/EvalResultBadges'
import { EvalsTabContent } from './components/EvalsTabContent'
import { EventContentDisplayAsync, EventContentGeneration } from './components/EventContentWithAsyncData'
import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { SentimentBar } from './components/SentimentTag'
import {
    ConversationDisplayOption,
    ConversationMessagesDisplay,
} from './ConversationDisplay/ConversationMessagesDisplay'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { SaveToDatasetButton } from './datasets/SaveToDatasetButton'
import { FeedbackViewDisplay } from './feedback-view/FeedbackViewDisplay'
import { useAIData } from './hooks/useAIData'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { DisplayOption, TraceViewMode, llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'
import { llmGenerationSentimentLazyLoaderLogic } from './llmGenerationSentimentLazyLoaderLogic'
import { LLMInputOutput } from './LLMInputOutput'
import { llmPersonsLazyLoaderLogic } from './llmPersonsLazyLoaderLogic'
import { llmSentimentLazyLoaderLogic } from './llmSentimentLazyLoaderLogic'
import { openInPlayground } from './playground/llmPlaygroundPromptsLogic'
import { ReviewQueuePickerModal } from './reviewQueues/ReviewQueuePickerModal'
import { reviewQueuesApi } from './reviewQueues/reviewQueuesApi'
import { SearchHighlight } from './SearchHighlight'
import { SENTIMENT_DATE_WINDOW_DAYS } from './sentimentUtils'
import { SummaryViewDisplay } from './summary-view/SummaryViewDisplay'
import { TextViewDisplay } from './text-view/TextViewDisplay'
import { exportTraceToClipboard } from './traceExportUtils'
import { TraceReviewButton } from './traceReviews/TraceReviewButton'
import { traceReviewModalLogic } from './traceReviews/traceReviewModalLogic'
import { traceReviewsLazyLoaderLogic } from './traceReviews/traceReviewsLazyLoaderLogic'
import { getTraceReviewTagItems } from './traceReviews/TraceReviewValue'
import { usePosthogAIBillingCalculations } from './usePosthogAIBillingCalculations'
import {
    CostContext,
    costContextFromProperties,
    costContextFromTrace,
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMLatency,
    formatLLMUsage,
    getEventType,
    getSessionStartTimestamp,
    getTraceTimestamp,
    hasCostBreakdown,
    isLLMEvent,
    normalizeMessages,
    removeMilliseconds,
    sanitizeTraceUrlSearchParams,
} from './utils'

interface TraceQueueContext {
    queueId: string | null
    isActive: boolean
    itemSearch: string
    itemOrderBy: string
}

interface TraceQueueAssignment {
    itemId: string
    queueId: string
    queueName: string
}

function getTraceQueueContext(searchParams: Record<string, unknown>): TraceQueueContext {
    const queueId = typeof searchParams.queue_id === 'string' && searchParams.queue_id ? searchParams.queue_id : null

    return {
        queueId,
        isActive: searchParams.back_to === 'reviews' && !!queueId,
        itemSearch: typeof searchParams.queue_item_search === 'string' ? searchParams.queue_item_search : '',
        itemOrderBy:
            typeof searchParams.queue_item_order_by === 'string' && searchParams.queue_item_order_by
                ? searchParams.queue_item_order_by
                : 'created_at',
    }
}

function getTraceReviewsBackPath(searchParams: Record<string, unknown>): string {
    const queueContext = getTraceQueueContext(searchParams)

    return combineUrl(urls.llmAnalyticsReviews(), {
        ...sanitizeTraceUrlSearchParams(searchParams),
        human_reviews_tab: queueContext.isActive ? undefined : 'reviews',
    }).url
}

function getQueueTracePath({
    traceId,
    searchParams,
    queueId,
    viewMode,
    itemSearch = '',
    itemOrderBy = 'created_at',
    previousTraceId,
    nextTraceId,
}: {
    traceId: string
    searchParams: Record<string, unknown>
    queueId: string
    viewMode: TraceViewMode
    itemSearch?: string
    itemOrderBy?: string
    previousTraceId?: string | null
    nextTraceId?: string | null
}): string {
    return combineUrl(urls.llmAnalyticsTrace(traceId), {
        ...sanitizeTraceUrlSearchParams(searchParams),
        back_to: 'reviews',
        human_reviews_tab: undefined,
        queue_id: queueId,
        queue_item_search: itemSearch || undefined,
        queue_item_order_by: itemOrderBy === 'created_at' ? undefined : itemOrderBy,
        queue_prev_trace_id: previousTraceId || undefined,
        queue_next_trace_id: nextTraceId || undefined,
        tab: viewMode,
    }).url
}

function QueueTraceNavigationButtons({
    traceId,
    queueId,
    itemSearch = '',
    itemOrderBy = 'created_at',
    showBackToQueue = false,
}: {
    traceId: string
    queueId: string
    itemSearch?: string
    itemOrderBy?: string
    showBackToQueue?: boolean
}): JSX.Element | null {
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { viewMode } = useValues(traceLogic)
    const { searchParams } = useValues(router)
    const fallbackPreviousTraceId =
        typeof searchParams.queue_prev_trace_id === 'string' && searchParams.queue_prev_trace_id
            ? searchParams.queue_prev_trace_id
            : null
    const fallbackNextTraceId =
        typeof searchParams.queue_next_trace_id === 'string' && searchParams.queue_next_trace_id
            ? searchParams.queue_next_trace_id
            : null
    const [queueTraceIds, setQueueTraceIds] = useState<string[] | null>(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        if (!queueId) {
            setQueueTraceIds(null)
            return
        }

        let isCancelled = false
        setLoading(true)

        void reviewQueuesApi
            .listQueueItems({
                queue_id: queueId,
                search: itemSearch || undefined,
                order_by: itemOrderBy,
                limit: 1000,
            })
            .then((response) => {
                if (!isCancelled) {
                    setQueueTraceIds(response.results.map((item) => item.trace_id))
                    setLoading(false)
                }
            })
            .catch(() => {
                if (!isCancelled) {
                    setQueueTraceIds(null)
                    setLoading(false)
                }
            })

        return () => {
            isCancelled = true
        }
    }, [itemOrderBy, itemSearch, queueId])

    const currentIndex = queueTraceIds?.indexOf(traceId) ?? -1
    const previousTraceId = currentIndex > 0 ? (queueTraceIds?.[currentIndex - 1] ?? null) : fallbackPreviousTraceId
    const fallbackIndex = fallbackNextTraceId ? (queueTraceIds?.indexOf(fallbackNextTraceId) ?? -1) : -1
    const nextTraceId = currentIndex >= 0 ? (queueTraceIds?.[currentIndex + 1] ?? null) : fallbackNextTraceId
    const previousOfPrevious = currentIndex > 1 ? (queueTraceIds?.[currentIndex - 2] ?? null) : null
    const followingTraceId =
        currentIndex >= 0
            ? (queueTraceIds?.[currentIndex + 2] ?? null)
            : fallbackIndex >= 0
              ? (queueTraceIds?.[fallbackIndex + 1] ?? null)
              : null
    const previousDisabledReason = loading
        ? 'Checking which trace comes before this one in the queue.'
        : 'This is the first trace in the queue.'
    const nextDisabledReason = loading
        ? 'Checking which trace comes after this one in the queue.'
        : 'This is the last trace in the queue.'

    const previousButton = (
        <LemonButton
            type="secondary"
            size="xsmall"
            disabled={!previousTraceId}
            loading={loading && !previousTraceId}
            onClick={() => {
                if (!previousTraceId) {
                    return
                }

                router.actions.push(
                    getQueueTracePath({
                        traceId: previousTraceId,
                        searchParams,
                        queueId,
                        viewMode,
                        itemSearch,
                        itemOrderBy,
                        previousTraceId: previousOfPrevious,
                        nextTraceId: traceId,
                    })
                )
            }}
            data-attr="llma-queue-previous-trace"
        >
            Previous
        </LemonButton>
    )
    const nextButton = (
        <LemonButton
            type="secondary"
            size="xsmall"
            disabled={!nextTraceId}
            loading={loading && !nextTraceId}
            onClick={() => {
                if (!nextTraceId) {
                    return
                }

                router.actions.push(
                    getQueueTracePath({
                        traceId: nextTraceId,
                        searchParams,
                        queueId,
                        viewMode,
                        itemSearch,
                        itemOrderBy,
                        previousTraceId: traceId,
                        nextTraceId: followingTraceId,
                    })
                )
            }}
            data-attr="llma-queue-next-trace"
        >
            Next
        </LemonButton>
    )

    return (
        <div className="flex flex-wrap items-center gap-2">
            {showBackToQueue ? (
                <LemonButton type="secondary" size="xsmall" to={getTraceReviewsBackPath(searchParams)}>
                    Back to queue
                </LemonButton>
            ) : null}
            {!previousTraceId ? (
                <Tooltip title={previousDisabledReason}>
                    <span className="inline-flex">{previousButton}</span>
                </Tooltip>
            ) : (
                previousButton
            )}
            {!nextTraceId ? (
                <Tooltip title={nextDisabledReason}>
                    <span className="inline-flex">{nextButton}</span>
                </Tooltip>
            ) : (
                nextButton
            )}
        </div>
    )
}

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
    useMountedLogic(traceReviewsLazyLoaderLogic)
    const { traceId, searchQuery, commentCount, viewMode } = useValues(traceLogic)
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
    const queueContext = getTraceQueueContext(searchParams)
    const previousQueueTraceId =
        typeof searchParams.queue_prev_trace_id === 'string' && searchParams.queue_prev_trace_id
            ? searchParams.queue_prev_trace_id
            : null
    const sanitizedBackSearchParams = sanitizeTraceUrlSearchParams(searchParams)
    const backPath =
        backTo === 'generations'
            ? combineUrl(urls.llmAnalyticsGenerations(), sanitizedBackSearchParams).url
            : backTo === 'reviews' && queueContext.isActive && queueContext.queueId && previousQueueTraceId && traceId
              ? getQueueTracePath({
                    traceId: previousQueueTraceId,
                    searchParams,
                    queueId: queueContext.queueId,
                    viewMode,
                    itemSearch: queueContext.itemSearch,
                    itemOrderBy: queueContext.itemOrderBy,
                    nextTraceId: traceId,
                })
              : backTo === 'reviews'
                ? getTraceReviewsBackPath(searchParams)
                : combineUrl(urls.llmAnalyticsTraces(), sanitizedBackSearchParams).url
    const forceBackTo =
        backTo === 'generations'
            ? { name: 'Generations', path: backPath, key: 'generations' }
            : backTo === 'reviews'
              ? { name: previousQueueTraceId ? 'Previous trace' : 'Reviews', path: backPath, key: 'reviews' }
              : { name: 'Traces', path: backPath, key: 'traces' }
    const showTraceNavigation = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRACE_NAVIGATION]

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
                    <div className="flex flex-col gap-4">
                        <SceneTitleSection
                            name={trace.id}
                            resourceType={{ type: 'llm_analytics' }}
                            forceBackTo={forceBackTo}
                            actions={showTraceNavigation ? <TraceNavigation /> : undefined}
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
                                <CopyTraceButton trace={trace} tree={enrichedTree} />
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
    tooltipTitle,
    children,
    icon,
    type,
    onClick,
    className,
}: {
    title: React.ReactNode
    tooltipTitle?: React.ReactNode
    children: React.ReactNode
    icon?: JSX.Element
    type?: LemonTagProps['type']
    onClick?: () => void
    className?: string
}): JSX.Element {
    const screenReaderTitle = typeof title === 'string' ? title : null

    return (
        <Tooltip title={tooltipTitle ?? title}>
            <LemonTag
                size="small"
                className={clsx('bg-surface-primary', className)}
                icon={icon}
                type={type}
                onClick={onClick}
            >
                {screenReaderTitle ? <span className="sr-only">{screenReaderTitle}</span> : null}
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

function CostChip({
    costContext,
    billedTotalUsd,
    billedCredits,
    markupUsd,
    showBillingInfo,
}: {
    costContext: CostContext
    billedTotalUsd?: number
    billedCredits?: number
    markupUsd?: number
    showBillingInfo?: boolean
}): JSX.Element {
    const hasBreakdown = hasCostBreakdown(costContext)
    const hasBilling = showBillingInfo && typeof billedTotalUsd === 'number' && billedTotalUsd > 0

    const tooltipContent =
        hasBreakdown || hasBilling ? (
            <CostBreakdownTooltip costContext={costContext}>
                {hasBilling && (
                    <>
                        <hr className="my-0.5 border-border" />
                        <div>Billed: {formatLLMCost(billedTotalUsd!)}</div>
                        {typeof markupUsd === 'number' && markupUsd > 0 && (
                            <div>Markup (20%): {formatLLMCost(markupUsd)}</div>
                        )}
                        {typeof billedCredits === 'number' && <div>Credits: {billedCredits}</div>}
                    </>
                )}
            </CostBreakdownTooltip>
        ) : undefined

    return (
        <Chip title="Total cost" tooltipTitle={tooltipContent} icon={<IconReceipt />}>
            {formatLLMCost(costContext.totalCost)}
        </Chip>
    )
}

function TraceWorkflowPanel({ traceId }: { traceId: string }): JSX.Element {
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { isTraceReviewPanelExpanded } = useValues(traceLogic)
    const { setTraceReviewPanelExpanded } = useActions(traceLogic)
    const { searchParams } = useValues(router)
    const queueContext = getTraceQueueContext(searchParams)
    const {
        getTraceReview,
        isTraceLoading: isTraceReviewLoading,
        didTraceReviewLoadFail,
    } = useValues(traceReviewsLazyLoaderLogic)
    const { ensureReviewsLoaded } = useActions(traceReviewsLazyLoaderLogic)
    const [queueAssignment, setQueueAssignment] = useState<TraceQueueAssignment | null>(null)
    const [queueAssignmentLoading, setQueueAssignmentLoading] = useState(false)
    const [queueMutationLoading, setQueueMutationLoading] = useState(false)
    const [queueAssignmentRefreshToken, setQueueAssignmentRefreshToken] = useState(0)

    const traceReview = getTraceReview(traceId)
    const traceReviewLoading = isTraceReviewLoading(traceId)
    const traceReviewLoadFailed = didTraceReviewLoadFail(traceId)

    useEffect(() => {
        if (!traceId || traceReview !== undefined || traceReviewLoading || traceReviewLoadFailed) {
            return
        }

        ensureReviewsLoaded([traceId])
    }, [ensureReviewsLoaded, traceId, traceReview, traceReviewLoadFailed, traceReviewLoading])

    useEffect(() => {
        let isCancelled = false
        setQueueAssignmentLoading(true)

        void reviewQueuesApi
            .listQueueItems({
                trace_id: traceId,
                limit: 1,
            })
            .then((response) => {
                if (isCancelled) {
                    return
                }

                const item = response.results[0]
                setQueueAssignment(
                    item
                        ? {
                              itemId: item.id,
                              queueId: item.queue_id,
                              queueName: item.queue_name,
                          }
                        : null
                )
                setQueueAssignmentLoading(false)
            })
            .catch(() => {
                if (!isCancelled) {
                    setQueueAssignment(null)
                    setQueueAssignmentLoading(false)
                }
            })

        return () => {
            isCancelled = true
        }
    }, [traceId, queueAssignmentRefreshToken])

    const reviewStatusSummary =
        traceReviewLoadFailed || traceReviewLoading || traceReview === undefined
            ? 'Checking review'
            : traceReview === null
              ? 'Not reviewed'
              : 'Reviewed'
    const reviewedWithoutQueue =
        !queueAssignmentLoading &&
        !traceReviewLoadFailed &&
        !traceReviewLoading &&
        traceReview !== undefined &&
        traceReview !== null &&
        !queueAssignment
    const queueStatusSummary = queueAssignmentLoading
        ? 'Checking queue'
        : queueAssignment
          ? `In ${queueAssignment.queueName}`
          : reviewedWithoutQueue
            ? "Can't be queued"
            : 'No queue'
    const panelSummary = `${reviewStatusSummary} · ${queueStatusSummary}`

    const removeFromQueue = (): void => {
        if (!queueAssignment || queueMutationLoading) {
            return
        }

        LemonDialog.open({
            title: `Remove from "${queueAssignment.queueName}"?`,
            primaryButton: {
                status: 'danger',
                children: 'Remove from queue',
                onClick: async () => {
                    setQueueMutationLoading(true)

                    try {
                        await reviewQueuesApi.deleteQueueItem(queueAssignment.itemId)
                        setQueueAssignment(null)
                        lemonToast.success(`Removed from "${queueAssignment.queueName}".`)
                    } catch {
                        lemonToast.error('Failed to remove the trace from its queue.')
                    } finally {
                        setQueueMutationLoading(false)
                    }
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const reviewTags =
        traceReview && !traceReviewLoading && !traceReviewLoadFailed
            ? getTraceReviewTagItems({ review: traceReview, maxVisibleScores: 3 })
            : []
    const currentQueueUrl = queueAssignment
        ? combineUrl(urls.llmAnalyticsReviews(), {
              human_reviews_tab: undefined,
              queue_id: queueAssignment.queueId,
          }).url
        : null
    const queueIdForReview = queueAssignment?.queueId ?? (queueContext.isActive ? queueContext.queueId : null)
    useMountedLogic(traceReviewModalLogic({ traceId, queueId: queueIdForReview }))
    const navigationQueueId = queueAssignment?.queueId ?? queueContext.queueId
    const navigationSearch = queueContext.isActive ? queueContext.itemSearch : ''
    const navigationOrderBy = queueContext.isActive ? queueContext.itemOrderBy : 'created_at'
    const removeFromQueueButton = queueAssignment ? (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="secondary"
                status="danger"
                size="xsmall"
                onClick={removeFromQueue}
                loading={queueMutationLoading}
                data-attr="llma-trace-remove-from-queue-button"
            >
                Remove
            </LemonButton>
        </AccessControlAction>
    ) : null

    const reviewActions: React.ReactNode[] = []
    if (traceReview === null) {
        reviewActions.push(
            <TraceReviewButton
                key="review-action"
                traceId={traceId}
                queueId={queueIdForReview}
                buttonType="primary"
                buttonSize="xsmall"
                buttonLabel="Review"
                onReviewSaved={() => setQueueAssignmentRefreshToken((token) => token + 1)}
            />
        )
    } else if (traceReview && !traceReviewLoading && !traceReviewLoadFailed) {
        reviewActions.push(
            <TraceReviewButton
                key="edit-review"
                traceId={traceId}
                queueId={queueIdForReview}
                buttonType="secondary"
                buttonSize="xsmall"
                buttonLabel="Edit"
                onReviewSaved={() => setQueueAssignmentRefreshToken((token) => token + 1)}
            />
        )
        if (removeFromQueueButton) {
            reviewActions.push(React.cloneElement(removeFromQueueButton, { key: 'remove-from-review' }))
        }
    }

    const queueActions: React.ReactNode[] = []
    if (queueAssignment) {
        queueActions.push(
            <ReviewQueuePickerModal
                key="move-queue"
                traceId={traceId}
                queueItemId={queueAssignment.itemId}
                defaultQueueId={queueAssignment.queueId}
                confirmLabel="Move queue"
                buttonType="secondary"
                buttonSize="xsmall"
                onSuccess={() => setQueueAssignmentRefreshToken((token) => token + 1)}
            />
        )
        if (!traceReview || traceReviewLoading || traceReviewLoadFailed) {
            queueActions.push(React.cloneElement(removeFromQueueButton as JSX.Element, { key: 'remove-from-queue' }))
        }
    } else if (traceReview === null) {
        queueActions.push(
            <ReviewQueuePickerModal
                key="add-queue"
                traceId={traceId}
                confirmLabel="Add to queue"
                buttonType="secondary"
                buttonSize="xsmall"
                onSuccess={() => setQueueAssignmentRefreshToken((token) => token + 1)}
            />
        )
    }

    return (
        <div className="border border-primary bg-surface-primary rounded overflow-hidden">
            <LemonCollapse
                embedded
                size="small"
                activeKey={isTraceReviewPanelExpanded ? 'workflow' : undefined}
                onChange={(activeKey) => setTraceReviewPanelExpanded(!!activeKey)}
                panels={[
                    {
                        key: 'workflow',
                        header: (
                            <div className="flex min-w-0 items-center gap-2 text-left">
                                <span className="shrink-0 text-sm font-medium">Trace review</span>
                                <span className="min-w-0 truncate text-xs text-muted">{panelSummary}</span>
                            </div>
                        ),
                        content: (
                            <div className="space-y-3 p-3">
                                <div className="space-y-2">
                                    <div className="text-sm text-muted">
                                        {traceReviewLoadFailed
                                            ? 'Review unavailable'
                                            : traceReviewLoading || traceReview === undefined
                                              ? 'Checking review…'
                                              : traceReview === null
                                                ? 'Not reviewed'
                                                : reviewTags.length > 0
                                                  ? `${pluralize(reviewTags.length, 'score', 'scores')} saved`
                                                  : 'Review saved'}
                                    </div>
                                    {reviewTags.length > 0 ? (
                                        <div className="space-y-1.5">
                                            {reviewTags.map((item) => (
                                                <div key={item.key}>
                                                    <LemonTag type={item.type} size="small">
                                                        {item.label}
                                                    </LemonTag>
                                                </div>
                                            ))}
                                        </div>
                                    ) : null}
                                    {reviewActions.length > 0 ? (
                                        <div className="flex flex-wrap items-center gap-2">{reviewActions}</div>
                                    ) : null}
                                </div>
                                <div className="space-y-2 border-t border-border pt-3">
                                    <div className="flex flex-wrap items-center gap-1.5 text-sm">
                                        {queueAssignmentLoading ? (
                                            <span className="text-muted">Checking queue…</span>
                                        ) : queueAssignment ? (
                                            <>
                                                <span className="text-muted">In queue</span>
                                                {currentQueueUrl ? (
                                                    <Link
                                                        to={currentQueueUrl}
                                                        target="_blank"
                                                        targetBlankIcon
                                                        className="font-medium"
                                                    >
                                                        {queueAssignment.queueName}
                                                    </Link>
                                                ) : (
                                                    <span className="font-medium">{queueAssignment.queueName}</span>
                                                )}
                                            </>
                                        ) : reviewedWithoutQueue ? (
                                            <span className="text-muted">
                                                This trace has been reviewed. It can't be added to a queue.
                                            </span>
                                        ) : (
                                            <span className="text-muted">No queue</span>
                                        )}
                                    </div>
                                    {queueActions.length > 0 ? (
                                        <div className="flex flex-wrap items-center gap-2">{queueActions}</div>
                                    ) : null}
                                </div>
                                {navigationQueueId ? (
                                    <div className="border-t border-border pt-3">
                                        <QueueTraceNavigationButtons
                                            traceId={traceId}
                                            queueId={navigationQueueId}
                                            itemSearch={navigationSearch}
                                            itemOrderBy={navigationOrderBy}
                                            showBackToQueue={queueContext.isActive}
                                        />
                                    </div>
                                ) : null}
                            </div>
                        ),
                        dataAttr: 'llma-trace-review-workflow-panel',
                    },
                ]}
            />
        </div>
    )
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
        ensureSentimentLoaded(trace.id, {
            dateFrom: trace.createdAt,
            dateTo: dayjs(trace.createdAt).add(SENTIMENT_DATE_WINDOW_DAYS, 'day').toISOString(),
        })
    }

    const traceCostContext = costContextFromTrace(trace)

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
            {traceCostContext && (
                <CostChip
                    costContext={traceCostContext}
                    billedTotalUsd={billedTotalUsd}
                    billedCredits={billedCredits}
                    markupUsd={markupUsd}
                    showBillingInfo={showBillingInfo}
                />
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
                        messages={sentimentResult.messages}
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
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    useMountedLogic(llmAnalyticsTraceDataLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchOccurrences } = useValues(llmAnalyticsTraceDataLogic)
    const { searchQuery } = useValues(traceLogic)
    const { setSearchQuery } = useActions(traceLogic)
    const showTraceWorkflow = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRACE_REVIEW]

    const [searchValue, setSearchValue] = useState(searchQuery)

    useEffect(() => {
        setSearchValue(searchQuery)
    }, [searchQuery])

    const debouncedSetSearchQuery = useDebouncedCallback((value: string) => {
        setSearchQuery(value)
    }, 300)

    const onSearchChange = (value: string): void => {
        setSearchValue(value)
        debouncedSetSearchQuery(value)
    }

    return (
        <aside
            className="sticky bottom-[var(--scene-padding)] max-h-fit flex flex-col gap-3 w-full md:w-80"
            id="trace-events-sidebar"
        >
            {showTraceWorkflow ? <TraceWorkflowPanel traceId={trace.id} /> : null}
            <div className="border border-primary bg-surface-primary rounded overflow-hidden flex flex-col">
                <h3 className="font-medium text-sm px-2 my-2">Tree</h3>
                <LemonDivider className="m-0" />
                <div className="p-2">
                    <LemonInput
                        placeholder="Search trace..."
                        prefix={<IconSearch />}
                        value={searchValue}
                        onChange={onSearchChange}
                        size="small"
                        data-attr="trace-search-input"
                    />
                    {searchValue.trim() && (
                        <div className="text-xs text-muted ml-1 mt-1">
                            {searchOccurrences.length > 0 ? (
                                <>
                                    {searchOccurrences.length}{' '}
                                    {searchOccurrences.length === 1 ? 'occurrence' : 'occurrences'}
                                </>
                            ) : (
                                'No occurrences'
                            )}
                        </div>
                    )}
                    <div className="mt-2">
                        <EventTypeFilters />
                    </div>
                </div>
                <ul className="overflow-y-auto p-1 *:first:mt-0 overflow-x-hidden">
                    <TreeNode
                        topLevelTrace={trace}
                        node={{
                            event: trace,
                            displayTotalCost: trace.totalCost || 0,
                            displayLatency: trace.totalLatency || 0,
                            displayUsage: formatLLMUsage(trace),
                        }}
                        isSelected={!eventId || eventId === trace.id}
                        searchQuery={searchQuery}
                        showBillingInfo={showBillingInfo}
                    />
                    <TreeNodeChildren
                        tree={tree}
                        trace={trace}
                        selectedEventId={eventId}
                        searchQuery={searchQuery}
                        showBillingInfo={showBillingInfo}
                    />
                </ul>
            </div>
        </aside>
    )
}

function NestingGroup({
    onToggle,
    isCollapsed,
    children,
}: {
    onToggle?: () => void
    isCollapsed?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <li className={clsx('flex items-stretch min-w-0', isCollapsed && 'text-border hover:text-muted')}>
            <div
                className={clsx('mb-1 ml-1 cursor-pointer', !isCollapsed && 'text-border hover:text-muted')}
                onClick={onToggle}
            >
                <div
                    className={clsx(
                        'w-0 h-full my-0 ml-1 mr-2 border-l border-current',
                        isCollapsed && 'border-dashed'
                    )}
                />
            </div>
            <ul className="flex-1 min-w-0">{children}</ul>
        </li>
    )
}

const TreeNode = React.memo(function TraceNode({
    topLevelTrace,
    node,
    isSelected,
    searchQuery,
    showBillingInfo,
}: {
    topLevelTrace: LLMTrace
    node:
        | EnrichedTraceTreeNode
        | { event: LLMTrace; displayTotalCost: number; displayLatency: number; displayUsage: string | null }
    isSelected: boolean
    searchQuery?: string
    showBillingInfo?: boolean
}): JSX.Element {
    const totalCost = node.displayTotalCost
    const latency = node.displayLatency
    const usage = node.displayUsage
    const item = node.event

    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { eventTypeExpanded } = useValues(traceLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const { getGenerationSentiment, isGenerationLoading } = useValues(llmGenerationSentimentLazyLoaderLogic)
    const { ensureGenerationSentimentLoaded } = useActions(llmGenerationSentimentLazyLoaderLogic)
    const eventType = getEventType(item)
    const isCollapsedDueToFilter = !eventTypeExpanded(eventType)
    const isBillable =
        showBillingInfo &&
        isLLMEvent(item) &&
        (item as LLMTraceEvent).event === '$ai_generation' &&
        !!(item as LLMTraceEvent).properties?.$ai_billable

    const showSentiment = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT]
    const isGeneration = isLLMEvent(item) && (item as LLMTraceEvent).event === '$ai_generation'
    const genSentiment = showSentiment && isGeneration ? getGenerationSentiment(item.id) : undefined
    if (showSentiment && isGeneration && genSentiment === undefined && !isGenerationLoading(item.id)) {
        ensureGenerationSentimentLoaded(item.id, {
            dateFrom: topLevelTrace.createdAt,
            dateTo: dayjs(topLevelTrace.createdAt).add(SENTIMENT_DATE_WINDOW_DAYS, 'day').toISOString(),
        })
    }

    const children = [
        isLLMEvent(item) && item.properties.$ai_is_error && (
            <LemonTag key="error-tag" type="danger">
                Error
            </LemonTag>
        ),
        latency >= 0.01 && (
            <LemonTag key="latency-tag" type="muted">
                {formatLLMLatency(latency)}
            </LemonTag>
        ),
        (usage != null || totalCost != null) && (
            <span key="usage-tag">
                {usage}
                {usage != null && totalCost != null && <span>{' / '}</span>}
                {totalCost != null && formatLLMCost(totalCost)}
            </span>
        ),
    ]
    const hasChildren = children.some((child) => !!child)

    return (
        <li key={item.id} className="mt-0.5" aria-current={isSelected /* aria-current used for auto-focus */}>
            <Link
                to={
                    combineUrl(urls.llmAnalyticsTrace(topLevelTrace.id), {
                        ...searchParams,
                        event: item.id,
                        timestamp: getTraceTimestamp(topLevelTrace.createdAt),
                        ...(searchQuery?.trim() && { search: searchQuery }),
                    }).url
                }
                className={clsx(
                    'flex flex-col gap-1 p-1 text-xs rounded min-h-8 justify-center hover:!bg-accent-highlight-secondary',
                    isSelected && '!bg-accent-highlight-secondary',
                    isCollapsedDueToFilter && 'min-h-4 min-w-0'
                )}
                data-attr="trace-event-link"
            >
                <div className="flex flex-row items-center gap-1.5">
                    <EventTypeTag event={item} size="small" />
                    {isBillable && (
                        <span title="Billable" aria-label="Billable" className="text-base">
                            💰
                        </span>
                    )}
                    {genSentiment && (
                        <SentimentBar
                            label={genSentiment.label}
                            score={genSentiment.score}
                            messages={genSentiment.messages}
                        />
                    )}
                    {!isCollapsedDueToFilter && (
                        <Tooltip title={formatLLMEventTitle(item)}>
                            {searchQuery?.trim() ? (
                                <SearchHighlight
                                    string={formatLLMEventTitle(item)}
                                    substring={searchQuery}
                                    className="flex-1"
                                />
                            ) : (
                                <span className="flex-1 truncate">{formatLLMEventTitle(item)}</span>
                            )}
                        </Tooltip>
                    )}
                </div>
                {!isCollapsedDueToFilter && renderModelRow(item, searchQuery)}
                {!isCollapsedDueToFilter && hasChildren && (
                    <div className="flex flex-row flex-wrap text-secondary items-center gap-1.5">{children}</div>
                )}
            </Link>
        </li>
    )
})

export function renderModelRow(event: LLMTrace | LLMTraceEvent, searchQuery?: string): React.ReactNode | null {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_generation') {
            // if we don't have a span name, we don't want to render the model row as its covered by the event title
            if (!event.properties.$ai_span_name) {
                return null
            }
            let model = event.properties.$ai_model
            if (event.properties.$ai_provider) {
                model = `${model} (${event.properties.$ai_provider})`
            }
            return searchQuery?.trim() ? (
                <SearchHighlight string={model} substring={searchQuery} className="flex-1" />
            ) : (
                <span className="flex-1 truncate"> {model} </span>
            )
        }
    }
    return null
}

function TreeNodeChildren({
    tree,
    trace,
    selectedEventId,
    searchQuery,
    showBillingInfo,
}: {
    tree: EnrichedTraceTreeNode[]
    trace: LLMTrace
    selectedEventId?: string | null
    searchQuery?: string
    showBillingInfo?: boolean
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)

    return (
        <NestingGroup isCollapsed={isCollapsed} onToggle={() => setIsCollapsed(!isCollapsed)}>
            {!isCollapsed ? (
                tree.map((node) => (
                    <React.Fragment key={node.event.id}>
                        <TreeNode
                            topLevelTrace={trace}
                            node={node}
                            isSelected={!!selectedEventId && selectedEventId === node.event.id}
                            searchQuery={searchQuery}
                            showBillingInfo={showBillingInfo}
                        />
                        {node.children && (
                            <TreeNodeChildren
                                tree={node.children}
                                trace={trace}
                                selectedEventId={selectedEventId}
                                searchQuery={searchQuery}
                                showBillingInfo={showBillingInfo}
                            />
                        )}
                    </React.Fragment>
                ))
            ) : (
                <div
                    className="text-secondary hover:text-default text-xxs cursor-pointer p-1"
                    onClick={() => setIsCollapsed(false)}
                >
                    Show {pluralize(tree.length, 'collapsed child', 'collapsed children')}
                </div>
            )}
        </NestingGroup>
    )
}

function EventContentDisplay({
    input,
    output,
    searchQuery,
    displayOption,
}: {
    input: unknown
    output: unknown
    searchQuery?: string
    displayOption?: ConversationDisplayOption
}): JSX.Element {
    if (!input && !output) {
        return <></>
    }

    const inputMessages = normalizeMessages(input, 'user')
    const outputMessages = normalizeMessages(output, 'assistant')

    if (inputMessages.length > 0 || outputMessages.length > 0) {
        return (
            <ConversationMessagesDisplay
                inputNormalized={inputMessages}
                outputNormalized={outputMessages}
                errorData={undefined}
                searchQuery={searchQuery}
                displayOption={displayOption}
            />
        )
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
                <div className="p-2 text-xs border rounded bg-[var(--color-bg-fill-success-tertiary)]">
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
        const traceDataLogic = useMountedLogic(llmAnalyticsTraceDataLogic)
        const { featureFlags } = useValues(featureFlagLogic)
        const { displayOption, lineNumber, initialTab, viewMode, highlightMessageIndex } = useValues(traceLogic)
        const { handleTextViewFallback, copyLinePermalink, setViewMode } = useActions(traceLogic)
        const { sessionId, selectedNode } = useValues(traceDataLogic)

        const aggregation = selectedNode?.aggregation || null

        const hasSessionRecording = !!sessionId

        const isGenerationEvent = event && isLLMEvent(event) && event.event === '$ai_generation'

        const promptName = event && isLLMEvent(event) ? event.properties['$ai_prompt_name'] : null
        const promptVersion = event && isLLMEvent(event) ? event.properties['$ai_prompt_version'] : null
        const showPromptButton = !!promptName

        const showPlaygroundButton = isGenerationEvent

        const showSaveToDatasetButton = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]

        const showEvalsTab = isGenerationEvent && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]

        const showSummaryTab =
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SUMMARIZATION] ||
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

        const showFeedbackTab = true

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

        const handleOpenInPlayground = (): void => {
            if (!event || !isLLMEvent(event)) {
                return
            }

            const model = event.properties.$ai_model
            const provider = event.properties.$ai_provider
            const tools = event.properties.$ai_tools

            openInPlayground({ model, provider, input: loadedInput, output: loadedOutput, tools })
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
                                    costContext={costContextFromProperties(event.properties)}
                                    model={event.properties.$ai_model}
                                    latency={event.properties.$ai_latency}
                                    timestamp={event.createdAt}
                                    timeToFirstToken={event.properties.$ai_time_to_first_token}
                                    isStreaming={event.properties.$ai_stream === true}
                                />
                            ) : (
                                <MetadataHeader
                                    inputTokens={event.inputTokens}
                                    outputTokens={event.outputTokens}
                                    costContext={costContextFromTrace(event)}
                                    latency={event.totalLatency}
                                    timestamp={event.createdAt}
                                />
                            )}
                            {isLLMEvent(event) && <ParametersHeader eventProperties={event.properties} />}
                            {(aggregation || showEvalsTab) && (
                                <div className="flex flex-col gap-1">
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
                                    {showEvalsTab && <EvalResultBadges generationEventId={event.id} />}
                                </div>
                            )}
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
                                            to={
                                                promptVersion
                                                    ? combineUrl(
                                                          urls.llmAnalyticsPrompt(promptName),
                                                          promptVersion ? { version: String(promptVersion) } : {}
                                                      ).url
                                                    : urls.llmAnalyticsPrompt(promptName)
                                            }
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
                                            icon={<IconPlay />}
                                            onClick={handleOpenInPlayground}
                                            tooltip="Open in Playground"
                                            data-attr="llma-playground-open-from-trace"
                                        >
                                            Open in Playground
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
                                            checkRecordingExists
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
                                                                traceId={trace.id}
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
                                                                displayOption={displayOption}
                                                                highlightMessageIndex={highlightMessageIndex}
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
                                                                searchQuery={searchQuery}
                                                                displayOption={displayOption}
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
                                {
                                    key: TraceViewMode.Clusters,
                                    label: 'Clusters',
                                    content: <ClustersTabContent />,
                                },
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

function EventTypeTag({ event, size }: { event: LLMTrace | LLMTraceEvent; size?: LemonTagProps['size'] }): JSX.Element {
    const eventType = getEventType(event)
    let tagType: LemonTagProps['type'] = 'completion'

    switch (eventType) {
        case 'generation':
            tagType = 'success'
            break
        case 'embedding':
            tagType = 'warning'
            break
        case 'span':
            tagType = 'default'
            break
        case 'trace':
            tagType = 'completion'
            break
    }

    return (
        <LemonTag className="uppercase" type={tagType} size={size}>
            {eventType}
        </LemonTag>
    )
}

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

function CopyTraceButton({ trace, tree }: { trace: LLMTrace; tree: EnrichedTraceTreeNode[] }): JSX.Element {
    const handleCopyTrace = async (): Promise<void> => {
        await exportTraceToClipboard(trace, tree)
    }

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconCopy />}
            onClick={handleCopyTrace}
            tooltip="Copy trace to clipboard"
            data-attr="copy-trace-json"
        >
            Copy trace JSON
        </LemonButton>
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
            value: DisplayOption.ExpandUserOnly,
            label: 'Expand user only',
            tooltip: 'Show only user messages in expanded view',
            'data-attr': 'llma-trace-display-expand-user-only',
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
