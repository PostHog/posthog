import { IconAIText, IconReceipt } from '@posthog/icons'
import { LemonDivider, LemonTag, LemonTagProps, Link, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import classNames from 'classnames'
import { BindLogic, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { NotFound } from 'lib/components/NotFound'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { range } from 'lib/utils'
import React from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema'

import { FeedbackTag } from './components/FeedbackTag'
import { MetricTag } from './components/MetricTag'
import { ConversationMessagesDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { LLMInputOutput } from './LLMInputOutput'
import { llmObservabilityTraceDataLogic } from './llmObservabilityTraceDataLogic'
import { llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage, isLLMTraceEvent, removeMilliseconds } from './utils'

export const scene: SceneExport = {
    component: LLMObservabilityTraceScene,
    logic: llmObservabilityTraceLogic,
}

export function LLMObservabilityTraceScene(): JSX.Element {
    const { traceId, query, cachedTraceResponse } = useValues(llmObservabilityTraceLogic)

    return (
        <BindLogic
            logic={llmObservabilityTraceDataLogic}
            props={{ traceId, query, cachedResults: cachedTraceResponse }}
        >
            <TraceSceneWrapper />
        </BindLogic>
    )
}

function TraceSceneWrapper(): JSX.Element {
    const { eventId } = useValues(llmObservabilityTraceLogic)
    const { trace, showableEvents, event, responseLoading, responseError, feedbackEvents, metricEvents } =
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
                <div className="relative space-y-4 flex flex-col md:h-[calc(100vh_-_var(--breadcrumbs-height-full)_-_var(--scene-padding)_-_var(--scene-padding-bottom))] ">
                    <TraceMetadata
                        trace={trace}
                        metricEvents={metricEvents as LLMTraceEvent[]}
                        feedbackEvents={feedbackEvents as LLMTraceEvent[]}
                    />
                    <div className="flex flex-1 min-h-0 gap-4 flex-col md:flex-row">
                        <TraceSidebar trace={trace} eventId={eventId} events={showableEvents} />
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
            <LemonTag size="medium" className="bg-bg-light" icon={icon}>
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
    events,
}: {
    trace: LLMTrace
    eventId?: string | null
    events: LLMTraceEvent[]
}): JSX.Element {
    return (
        <aside className="border-border max-h-fit bg-bg-light border rounded overflow-hidden md:w-72">
            <h3 className="font-medium text-sm px-2 my-2">Tree</h3>
            <LemonDivider className="m-0" />
            <NestingGroup>
                <TraceNode topLevelTrace={trace} item={trace} isSelected={!eventId || eventId === trace.id} />
                <NestingGroup level={1}>
                    {events.map((event) => (
                        <TraceNode
                            topLevelTrace={trace}
                            key={event.id}
                            item={event}
                            isSelected={!!eventId && eventId === event.id}
                        />
                    ))}
                </NestingGroup>
            </NestingGroup>
        </aside>
    )
}

function NestingGroup({ level = 0, children }: { level?: number; children: React.ReactNode }): JSX.Element {
    const listEl = <ul className={!level ? 'overflow-y-auto p-1 first:*:mt-0' : 'flex-1'}>{children}</ul>

    if (!level) {
        return listEl
    }

    return (
        <div className="flex items-stretch">
            {range(level).map((i) => (
                <LemonDivider key={i} vertical className="mt-0 mb-1 mx-2" />
            ))}
            {listEl}
        </div>
    )
}

function TraceNode({
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

    return (
        <li key={item.id} className="mt-0.5">
            <Link
                to={urls.llmObservabilityTrace(topLevelTrace.id, {
                    event: item.id,
                    timestamp: removeMilliseconds(topLevelTrace.createdAt),
                })}
                className={classNames(
                    'flex flex-col gap-1 p-1 text-xs rounded hover:bg-accent-primary-highlight',
                    isSelected && 'bg-accent-primary-highlight'
                )}
            >
                <div className="flex flex-row flex-wrap items-center gap-1.5">
                    <EventTypeTag event={item} size="small" />
                    <span>
                        {'properties' in item
                            ? `${item.properties.$ai_model} (${item.properties.$ai_provider})`
                            : item.traceName}
                    </span>
                </div>
                <div className="flex flex-row flex-wrap text-muted items-center gap-1.5">
                    <LemonTag type="muted">{formatLLMLatency(latency)}</LemonTag>
                    {(usage != null || totalCost != null) && (
                        <span>
                            {usage}
                            {usage != null && totalCost != null && <span>{' / '}</span>}
                            {totalCost != null && formatLLMCost(totalCost)}
                        </span>
                    )}
                </div>
            </Link>
        </li>
    )
}

function EventContent({ event }: { event: LLMTrace | LLMTraceEvent | null }): JSX.Element {
    return (
        <div className="flex-1 bg-bg-light max-h-fit border rounded flex flex-col border-border p-4 overflow-y-auto">
            {!event ? (
                <InsightEmptyState heading="Event not found" detail="Check if the event ID is correct." />
            ) : (
                <>
                    <header className="space-y-2">
                        <div className="flex-row flex items-center gap-2">
                            <EventTypeTag event={event} />
                            <h3 className="text-lg font-semibold p-0 m-0">
                                {isLLMTraceEvent(event)
                                    ? `${event.properties.$ai_model} (${event.properties.$ai_provider})`
                                    : event.traceName}
                            </h3>
                        </div>
                        {isLLMTraceEvent(event) ? (
                            <MetadataHeader
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
                    </header>
                    <LemonDivider className="my-3" />
                    {isLLMTraceEvent(event) ? (
                        <ConversationMessagesDisplay
                            input={event.properties.$ai_input}
                            output={event.properties.$ai_output_choices || event.properties.$ai_output}
                            httpStatus={event.properties.$ai_http_status}
                        />
                    ) : (
                        <LLMInputOutput
                            inputDisplay={
                                <div className="p-2 text-xs border rounded bg-[var(--bg-fill-tertiary)]">
                                    {event.inputState != null &&
                                    typeof event.inputState !== 'number' &&
                                    typeof event.inputState !== 'string' &&
                                    typeof event.inputState !== 'boolean' ? (
                                        <JSONViewer src={event.inputState || null} collapsed={4} />
                                    ) : (
                                        <span className="font-mono">{JSON.stringify(event.inputState ?? null)}</span>
                                    )}
                                </div>
                            }
                            outputDisplay={
                                <div className="p-2 text-xs border rounded bg-[var(--bg-fill-success-tertiary)]">
                                    {event.outputState ? (
                                        <JSONViewer src={event.outputState} collapsed={4} />
                                    ) : (
                                        <span className="font-mono">{JSON.stringify(event.outputState ?? null)}</span>
                                    )}
                                </div>
                            }
                        />
                    )}
                </>
            )}
        </div>
    )
}

function EventTypeTag({ event, size }: { event: LLMTrace | LLMTraceEvent; size?: LemonTagProps['size'] }): JSX.Element {
    const eventType = isLLMTraceEvent(event) && event.properties.$ai_model ? 'generation' : 'trace'
    return (
        <LemonTag className="uppercase" type={eventType === 'trace' ? 'completion' : 'default'} size={size}>
            {eventType}
        </LemonTag>
    )
}
