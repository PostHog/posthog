import classNames from 'classnames'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconAIText, IconChat, IconCopy, IconMessage, IconReceipt, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
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

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman, isObject, pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { ConversationMessagesDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { LLMInputOutput } from './LLMInputOutput'
import { SearchHighlight } from './SearchHighlight'
import { EvalsTabContent } from './components/EvalsTabContent'
import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { SummaryTabContent } from './components/SummaryTabContent'
import { SaveToDatasetButton } from './datasets/SaveToDatasetButton'
import { llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { DisplayOption, llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'
import { TextViewDisplay } from './text-view/TextViewDisplay'
import { exportTraceToClipboard } from './traceExportUtils'
import {
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMLatency,
    formatLLMUsage,
    getEventType,
    getSessionID,
    getTraceTimestamp,
    isLLMEvent,
    normalizeMessages,
    removeMilliseconds,
} from './utils'

enum TraceViewMode {
    Conversation = 'conversation',
    Raw = 'raw',
    Summary = 'summary',
    Evals = 'evals',
}

export const scene: SceneExport = {
    component: LLMAnalyticsTraceScene,
    logic: llmAnalyticsTraceLogic,
}

export function LLMAnalyticsTraceScene(): JSX.Element {
    const { traceId, query } = useValues(llmAnalyticsTraceLogic)

    return (
        <BindLogic logic={llmAnalyticsTraceDataLogic} props={{ traceId, query }}>
            <TraceSceneWrapper />
        </BindLogic>
    )
}

function TraceSceneWrapper(): JSX.Element {
    const { eventId } = useValues(llmAnalyticsTraceLogic)
    const {
        enrichedTree,
        trace,
        event,
        responseLoading,
        responseError,
        feedbackEvents,
        metricEvents,
        searchQuery,
        eventMetadata,
    } = useValues(llmAnalyticsTraceDataLogic)

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
                        />
                        <div className="flex flex-wrap justify-end items-center gap-x-2 gap-y-1">
                            <DisplayOptionsSelect />
                            <CopyTraceButton trace={trace} tree={enrichedTree} />
                        </div>
                    </div>
                    <div className="flex flex-1 min-h-0 gap-3 flex-col md:flex-row">
                        <TraceSidebar trace={trace} eventId={eventId} tree={enrichedTree} />
                        <EventContent
                            trace={trace}
                            event={event}
                            tree={enrichedTree}
                            searchQuery={searchQuery}
                            eventMetadata={eventMetadata}
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
}: {
    trace: LLMTrace
    metricEvents: LLMTraceEvent[]
    feedbackEvents: LLMTraceEvent[]
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const getSessionUrl = (sessionId: string): string => {
        if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW]) {
            return urls.llmAnalyticsSession(sessionId)
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
                        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW]
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
}: {
    trace: LLMTrace
    eventId?: string | null
    tree: EnrichedTraceTreeNode[]
}): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { mostRelevantEvent, searchOccurrences } = useValues(llmAnalyticsTraceDataLogic)
    const { searchQuery } = useValues(llmAnalyticsTraceLogic)
    const { setSearchQuery, setEventId } = useActions(llmAnalyticsTraceLogic)

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

    useEffect(() => {
        if (eventId && ref.current) {
            const selectedNode = ref.current.querySelector(`[aria-current=true]`)
            if (selectedNode) {
                selectedNode.scrollIntoView({ block: 'center' })
            }
        }
    }, [eventId])

    useEffect(() => {
        if (mostRelevantEvent && searchQuery.trim()) {
            setEventId(mostRelevantEvent.id)
        }
    }, [mostRelevantEvent, searchQuery, setEventId])

    return (
        <aside
            className="sticky bottom-[var(--scene-padding)] border-primary max-h-fit bg-surface-primary border rounded overflow-hidden flex flex-col w-full md:w-80"
            ref={ref}
        >
            <h3 className="font-medium text-sm px-2 my-2">Tree</h3>
            <LemonDivider className="m-0" />
            <div className="p-2">
                <LemonInput
                    placeholder="Search trace..."
                    prefix={<IconSearch />}
                    value={searchValue}
                    onChange={onSearchChange}
                    size="small"
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
                />
                <TreeNodeChildren tree={tree} trace={trace} selectedEventId={eventId} searchQuery={searchQuery} />
            </ul>
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
}: {
    topLevelTrace: LLMTrace
    node:
        | EnrichedTraceTreeNode
        | { event: LLMTrace; displayTotalCost: number; displayLatency: number; displayUsage: string | null }
    isSelected: boolean
    searchQuery?: string
}): JSX.Element {
    const totalCost = node.displayTotalCost
    const latency = node.displayLatency
    const usage = node.displayUsage
    const item = node.event

    const { eventTypeExpanded } = useValues(llmAnalyticsTraceLogic)
    const eventType = getEventType(item)
    const isCollapsedDueToFilter = !eventTypeExpanded(eventType)

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
                to={urls.llmAnalyticsTrace(topLevelTrace.id, {
                    event: item.id,
                    timestamp: getTraceTimestamp(topLevelTrace.createdAt),
                    ...(searchQuery?.trim() && { search: searchQuery }),
                })}
                className={classNames(
                    'flex flex-col gap-1 p-1 text-xs rounded min-h-8 justify-center hover:!bg-accent-highlight-secondary',
                    isSelected && '!bg-accent-highlight-secondary',
                    isCollapsedDueToFilter && 'min-h-4 min-w-0'
                )}
            >
                <div className="flex flex-row items-center gap-1.5">
                    <EventTypeTag event={item} size="small" />
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
}: {
    tree: EnrichedTraceTreeNode[]
    trace: LLMTrace
    selectedEventId?: string | null
    searchQuery?: string
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
                        />
                        {node.children && (
                            <TreeNodeChildren
                                tree={node.children}
                                trace={trace}
                                selectedEventId={selectedEventId}
                                searchQuery={searchQuery}
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
    }: {
        trace: LLMTrace
        event: LLMTrace | LLMTraceEvent | null
        tree: EnrichedTraceTreeNode[]
        searchQuery?: string
        eventMetadata?: Record<string, unknown>
    }): JSX.Element => {
        const { setupPlaygroundFromEvent } = useActions(llmAnalyticsPlaygroundLogic)
        const { featureFlags } = useValues(featureFlagLogic)
        const { displayOption, lineNumber } = useValues(llmAnalyticsTraceLogic)
        const { setDisplayOption } = useActions(llmAnalyticsTraceLogic)

        const [viewMode, setViewMode] = useState(TraceViewMode.Conversation)

        const node = event && isLLMEvent(event) ? findNodeForEvent(tree, event.id) : null
        const aggregation = node?.aggregation || null

        const childEventsForSessionId: LLMTraceEvent[] | undefined = node?.children?.map((child) => child.event)
        const sessionId = event ? getSessionID(event, childEventsForSessionId) : null
        const hasSessionRecording = !!sessionId

        const isGenerationEvent = event && isLLMEvent(event) && event.event === '$ai_generation'

        const showPlaygroundButton = isGenerationEvent && featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_PLAYGROUND]

        const showSaveToDatasetButton = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]

        const showEvalsTab = isGenerationEvent && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]

        const showSummaryTab = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SUMMARIZATION]

        const handleTryInPlayground = (): void => {
            if (!event) {
                return
            }

            let model: string | undefined = undefined
            let input: any = undefined
            let tools: any = undefined

            if (isLLMEvent(event)) {
                model = event.properties.$ai_model
                // Prefer $ai_input if available, otherwise fallback to $ai_input_state
                input = event.properties.$ai_input ?? event.properties.$ai_input_state
                tools = event.properties.$ai_tools
            }

            setupPlaygroundFromEvent({ model, input, tools })
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
                                        >
                                            Try in Playground
                                        </LemonButton>
                                    )}
                                    {showSaveToDatasetButton && (
                                        <SaveToDatasetButton
                                            traceId={trace.id}
                                            timestamp={trace.createdAt}
                                            sourceId={event.id}
                                            input={
                                                isLLMEvent(event)
                                                    ? (event.properties.$ai_input ?? event.properties.$ai_input_state)
                                                    : event.inputState
                                            }
                                            output={
                                                isLLMEvent(event)
                                                    ? (event.properties.$ai_output_choices ??
                                                      event.properties.$ai_output ??
                                                      event.properties.$ai_output_state ??
                                                      event.properties.$ai_error)
                                                    : event.outputState
                                            }
                                            metadata={eventMetadata}
                                        />
                                    )}
                                    {hasSessionRecording && (
                                        <ViewRecordingButton
                                            inModal
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
                                    content: (
                                        <>
                                            {displayOption === DisplayOption.TextView &&
                                            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TEXT_VIEW] ? (
                                                isLLMEvent(event) &&
                                                (event.event === '$ai_generation' ||
                                                    event.event === '$ai_span' ||
                                                    event.event === '$ai_embedding') ? (
                                                    <TextViewDisplay
                                                        event={event}
                                                        lineNumber={lineNumber}
                                                        onFallback={() => setDisplayOption(DisplayOption.ExpandAll)}
                                                    />
                                                ) : !isLLMEvent(event) ? (
                                                    <TextViewDisplay
                                                        trace={event}
                                                        tree={tree}
                                                        lineNumber={lineNumber}
                                                        onFallback={() => setDisplayOption(DisplayOption.ExpandAll)}
                                                    />
                                                ) : null
                                            ) : (
                                                <>
                                                    {isLLMEvent(event) ? (
                                                        event.event === '$ai_generation' ? (
                                                            <ConversationMessagesDisplay
                                                                inputNormalized={normalizeMessages(
                                                                    event.properties.$ai_input,
                                                                    'user',
                                                                    event.properties.$ai_tools
                                                                )}
                                                                outputNormalized={normalizeMessages(
                                                                    event.properties.$ai_output_choices ??
                                                                        event.properties.$ai_output,
                                                                    'assistant'
                                                                )}
                                                                errorData={event.properties.$ai_error}
                                                                httpStatus={event.properties.$ai_http_status}
                                                                raisedError={event.properties.$ai_is_error}
                                                                searchQuery={searchQuery}
                                                            />
                                                        ) : event.event === '$ai_embedding' ? (
                                                            <EventContentDisplay
                                                                input={event.properties.$ai_input}
                                                                output="Embedding vector generated"
                                                            />
                                                        ) : (
                                                            <EventContentDisplay
                                                                input={event.properties.$ai_input_state}
                                                                output={
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
                                              content: (
                                                  <SummaryTabContent
                                                      trace={!isLLMEvent(event) ? event : undefined}
                                                      event={isLLMEvent(event) ? event : undefined}
                                                      tree={tree}
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
                                              content: (
                                                  <EvalsTabContent
                                                      generationEventId={event.id}
                                                      timestamp={event.createdAt}
                                                  />
                                              ),
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
        >
            Copy trace JSON
        </LemonButton>
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
        },
        {
            value: DisplayOption.CollapseExceptOutputAndLastInput,
            label: 'Collapse except output and last input',
            tooltip: 'Focus on the most recent input and final output',
        },
        ...(featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TEXT_VIEW]
            ? [
                  {
                      value: DisplayOption.TextView,
                      label: 'Text view',
                      tooltip: 'Simple human readable text view, for humans',
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
