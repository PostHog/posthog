import { IconAIText, IconChat, IconMessage, IconReceipt } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonTable,
    LemonTag,
    LemonTagProps,
    Link,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import classNames from 'classnames'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import { IconArrowDown, IconArrowUp, IconOpenInNew } from 'lib/lemon-ui/icons'
import { identifierToHuman, isObject, pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import React, { useEffect, useRef, useState } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { ConversationMessagesDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { LLMInputOutput } from './LLMInputOutput'
import { llmObservabilityPlaygroundLogic } from './llmObservabilityPlaygroundLogic'
import { llmObservabilityTraceDataLogic, TraceTreeNode } from './llmObservabilityTraceDataLogic'
import { llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'
import {
    formatLLMCost,
    formatLLMEventTitle,
    formatLLMLatency,
    formatLLMUsage,
    getSessionID,
    hasSessionID,
    isLLMTraceEvent,
    removeMilliseconds,
} from './utils'

export const scene: SceneExport = {
    component: LLMObservabilityTraceScene,
    logic: llmObservabilityTraceLogic,
}

export function LLMObservabilityTraceScene(): JSX.Element {
    const { traceId, query } = useValues(llmObservabilityTraceLogic)

    return (
        <BindLogic logic={llmObservabilityTraceDataLogic} props={{ traceId, query }}>
            <TraceSceneWrapper />
        </BindLogic>
    )
}

function TraceSceneWrapper(): JSX.Element {
    const { eventId } = useValues(llmObservabilityTraceLogic)
    const { tree, trace, event, responseLoading, responseError, feedbackEvents, metricEvents } =
        useValues(llmObservabilityTraceDataLogic)

    return (
        <>
            {responseLoading ? (
                <SpinnerOverlay />
            ) : responseError ? (
                <InsightErrorState />
            ) : !trace ? (
                <NotFound object="trace" />
            ) : (
                <div className="relative deprecated-space-y-4 flex flex-col md:h-[calc(100vh_-_var(--breadcrumbs-height-full)_-_var(--scene-padding)_-_var(--scene-padding-bottom))] ">
                    <TraceMetadata
                        trace={trace}
                        metricEvents={metricEvents as LLMTraceEvent[]}
                        feedbackEvents={feedbackEvents as LLMTraceEvent[]}
                    />
                    <div className="flex flex-1 min-h-0 gap-4 flex-col md:flex-row">
                        <TraceSidebar trace={trace} eventId={eventId} tree={tree} />
                        <EventContent event={event} />
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
    return (
        <header className="flex gap-2 flex-wrap">
            {'person' in trace && (
                <Chip title="Person">
                    <PersonDisplay withIcon="sm" person={trace.person} />
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
    tree: TraceTreeNode[]
}): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        // On first render, let's focus the selected tree node in the center
        if (eventId && ref.current) {
            const selectedNode = ref.current.querySelector(`[aria-current=true]`)
            if (selectedNode) {
                selectedNode.scrollIntoView({ block: 'center' })
            }
        }
    }, [eventId])

    return (
        <aside
            className="border-primary max-h-fit bg-surface-primary border rounded overflow-hidden flex flex-col md:w-80"
            ref={ref}
        >
            <h3 className="font-medium text-sm px-2 my-2">Tree</h3>
            <LemonDivider className="m-0" />
            <ul className="overflow-y-auto p-1 *:first:mt-0 overflow-x-hidden">
                <TreeNode topLevelTrace={trace} item={trace} isSelected={!eventId || eventId === trace.id} />
                <TreeNodeChildren tree={tree} trace={trace} selectedEventId={eventId} />
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
    item,
    isSelected,
}: {
    topLevelTrace: LLMTrace
    item: LLMTrace | LLMTraceEvent
    isSelected: boolean
}): JSX.Element {
    const totalCost = 'properties' in item ? item.properties.$ai_total_cost_usd : item.totalCost
    const latency = 'properties' in item ? item.properties.$ai_latency : item.totalLatency
    const usage = formatLLMUsage(item)

    const children = [
        isLLMTraceEvent(item) && item.properties.$ai_is_error && (
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
                to={urls.llmObservabilityTrace(topLevelTrace.id, {
                    event: item.id,
                    timestamp: removeMilliseconds(topLevelTrace.createdAt),
                })}
                className={classNames(
                    'flex flex-col gap-1 p-1 text-xs rounded min-h-8 justify-center hover:!bg-accent-highlight-secondary',
                    isSelected && '!bg-accent-highlight-secondary'
                )}
            >
                <div className="flex flex-row items-center gap-1.5">
                    <EventTypeTag event={item} size="small" />
                    <Tooltip title={formatLLMEventTitle(item)}>
                        <span className="flex-1 truncate">{formatLLMEventTitle(item)}</span>
                    </Tooltip>
                </div>
                {renderModelRow(item)}
                {hasChildren && (
                    <div className="flex flex-row flex-wrap text-secondary items-center gap-1.5">{children}</div>
                )}
            </Link>
        </li>
    )
})

export function renderModelRow(event: LLMTrace | LLMTraceEvent): React.ReactNode | null {
    if (isLLMTraceEvent(event)) {
        if (event.event === '$ai_generation') {
            // if we don't have a span name, we don't want to render the model row as its covered by the event title
            if (!event.properties.$ai_span_name) {
                return null
            }
            let model = event.properties.$ai_model
            if (event.properties.$ai_provider) {
                model = `${model} (${event.properties.$ai_provider})`
            }
            return <span className="flex-1 truncate"> {model} </span>
        }
    }
    return null
}

function TreeNodeChildren({
    tree,
    trace,
    selectedEventId,
}: {
    tree: TraceTreeNode[]
    trace: LLMTrace
    selectedEventId?: string | null
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)

    return (
        <NestingGroup isCollapsed={isCollapsed} onToggle={() => setIsCollapsed(!isCollapsed)}>
            {!isCollapsed ? (
                tree.map(({ event, children }) => (
                    <React.Fragment key={event.id}>
                        <TreeNode
                            topLevelTrace={trace}
                            item={event}
                            isSelected={!!selectedEventId && selectedEventId === event.id}
                        />
                        {children && (
                            <TreeNodeChildren tree={children} trace={trace} selectedEventId={selectedEventId} />
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
    if (!input && !output) {
        // If we have no data here we should not render anything
        // In future plan to point docs to show how to add custom trace events
        return <></>
    }
    return (
        <LLMInputOutput
            inputDisplay={
                <div className="p-2 text-xs border rounded bg-[var(--bg-fill-secondary)]">
                    {isObject(input) ? (
                        <JSONViewer src={input} collapsed={4} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(input ?? null)}</span>
                    )}
                </div>
            }
            outputDisplay={
                <div
                    className={cn(
                        'p-2 text-xs border rounded',
                        !raisedError ? 'bg-[var(--bg-fill-success-tertiary)]' : 'bg-[var(--bg-fill-error-tertiary)]'
                    )}
                >
                    {isObject(output) ? (
                        <JSONViewer src={output} collapsed={4} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(output ?? null)}</span>
                    )}
                </div>
            }
        />
    )
}

const EventContent = React.memo(({ event }: { event: LLMTrace | LLMTraceEvent | null }): JSX.Element => {
    const { setupPlaygroundFromEvent } = useActions(llmObservabilityPlaygroundLogic)

    const showPlaygroundButton = event && isLLMTraceEvent(event) && event.event === '$ai_generation'

    const handleTryInPlayground = (): void => {
        if (!event) {
            return
        }

        let model: string | undefined = undefined
        let input: any = undefined

        if (isLLMTraceEvent(event)) {
            model = event.properties.$ai_model
            // Prefer $ai_input if available, otherwise fallback to $ai_input_state
            input = event.properties.$ai_input ?? event.properties.$ai_input_state
        }

        setupPlaygroundFromEvent({ model, input })
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
                        {isLLMTraceEvent(event) ? (
                            <MetadataHeader
                                isError={event.properties.$ai_is_error}
                                inputTokens={event.properties.$ai_input_tokens}
                                outputTokens={event.properties.$ai_output_tokens}
                                totalCostUsd={event.properties.$ai_total_cost_usd}
                                model={event.properties.$ai_model}
                                latency={event.properties.$ai_latency}
                            />
                        ) : (
                            <MetadataHeader
                                inputTokens={event.inputTokens}
                                outputTokens={event.outputTokens}
                                totalCostUsd={event.totalCost}
                                latency={event.totalLatency}
                            />
                        )}
                        {isLLMTraceEvent(event) && <ParametersHeader eventProperties={event.properties} />}
                        <div className="flex flex-row items-center gap-2">
                            {showPlaygroundButton && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconChat />}
                                    onClick={handleTryInPlayground}
                                    tooltip="Try this prompt in the playground"
                                >
                                    Try in Playground
                                </LemonButton>
                            )}
                            {hasSessionID(event) && (
                                <div className="flex flex-row items-center gap-2">
                                    <Link
                                        to={urls.replay(undefined, undefined, getSessionID(event) ?? '')}
                                        className="flex flex-row gap-1 items-center"
                                    >
                                        <IconOpenInNew />
                                        <span>View session recording</span>
                                    </Link>
                                </div>
                            )}
                        </div>
                    </header>
                    {isLLMTraceEvent(event) ? (
                        event.event === '$ai_generation' ? (
                            <ConversationMessagesDisplay
                                tools={event.properties.$ai_tools}
                                input={event.properties.$ai_input}
                                output={
                                    event.properties.$ai_is_error
                                        ? event.properties.$ai_error
                                        : event.properties.$ai_output_choices ?? event.properties.$ai_output
                                }
                                httpStatus={event.properties.$ai_http_status}
                                raisedError={event.properties.$ai_is_error}
                            />
                        ) : (
                            <EventContentDisplay
                                input={event.properties.$ai_input_state}
                                output={event.properties.$ai_output_state ?? event.properties.$ai_error}
                                raisedError={event.properties.$ai_is_error}
                            />
                        )
                    ) : (
                        <>
                            <TraceMetricsTable />
                            <EventContentDisplay input={event.inputState} output={event.outputState} />
                        </>
                    )}
                </>
            )}
        </div>
    )
})
EventContent.displayName = 'EventContent'

function EventTypeTag({ event, size }: { event: LLMTrace | LLMTraceEvent; size?: LemonTagProps['size'] }): JSX.Element {
    let eventType = 'trace'
    if (isLLMTraceEvent(event)) {
        eventType = event.event === '$ai_generation' ? 'generation' : 'span'
    }
    return (
        <LemonTag
            className="uppercase"
            type={eventType === 'trace' ? 'completion' : eventType === 'span' ? 'default' : 'success'}
            size={size}
        >
            {eventType}
        </LemonTag>
    )
}

function TraceMetricsTable(): JSX.Element | null {
    const { metricsAndFeedbackEvents } = useValues(llmObservabilityTraceDataLogic)

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
