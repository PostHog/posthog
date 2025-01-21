import { PersonDisplay, urls } from '@posthog/apps-common'
import { LemonDivider, LemonTag, Link, SpinnerOverlay } from '@posthog/lemon-ui'
import classNames from 'classnames'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import React, { useMemo } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LLMTrace, LLMTraceEvent, TracesQueryResponse } from '~/queries/schema'

import { ConversationMessagesDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { getDataNodeLogicProps, llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage } from './utils'

export const scene: SceneExport = {
    component: LLMObservabilityTraceScene,
    logic: llmObservabilityTraceLogic,
}

export function LLMObservabilityTraceScene(): JSX.Element {
    const { traceId, query, eventId, cachedTraceResponse } = useValues(llmObservabilityTraceLogic)

    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic(getDataNodeLogicProps({ traceId, query, cachedResults: cachedTraceResponse }))
    )

    const traceResponse = response as TracesQueryResponse | null
    const event = useMemo(() => {
        const trace = traceResponse?.results?.[0]
        if (!trace) {
            return undefined
        }
        return eventId ? trace.events.find((event) => event.id === eventId) : trace.events[0]
    }, [traceResponse, eventId])

    return (
        <>
            {responseLoading ? (
                <SpinnerOverlay />
            ) : responseError ? (
                <InsightErrorState />
            ) : !traceResponse || traceResponse.results.length === 0 ? (
                <NotFound object="trace" />
            ) : (
                <div className="relative pb-4 space-y-4 flex flex-col md:h-[calc(100vh_-_var(--breadcrumbs-height-full)_-_var(--scene-padding)_-_var(--scene-padding-bottom))] ">
                    <TraceMetadata trace={traceResponse.results[0]} />
                    <div className="flex flex-1 min-h-0 gap-4 flex-col md:flex-row">
                        <TraceSidebar trace={traceResponse.results[0]} eventId={eventId} />
                        <EventContent event={event} />
                    </div>
                </div>
            )}
        </>
    )
}

function Chip({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <span className="font-medium">{title}</span>
            <span>{children}</span>
        </div>
    )
}

function UsageChip({ event }: { event: LLMTraceEvent | LLMTrace }): JSX.Element | null {
    const usage = formatLLMUsage(event)
    return usage ? <Chip title="Usage">{usage}</Chip> : null
}

function CostChip({ cost, title }: { cost: number; title: string }): JSX.Element {
    return <Chip title={title}>{formatLLMCost(cost)}</Chip>
}

function TraceMetadata({ trace }: { trace: LLMTrace }): JSX.Element {
    return (
        <header className="flex gap-x-8 gap-y-2 flex-wrap border border-border rounded p-4 bg-bg-light text-sm">
            {'person' in trace && (
                <Chip title="Person">
                    <PersonDisplay withIcon="sm" person={trace.person} />
                </Chip>
            )}
            <UsageChip event={trace} />
            {typeof trace.inputCost === 'number' && <CostChip cost={trace.inputCost} title="Input cost" />}
            {typeof trace.outputCost === 'number' && <CostChip cost={trace.outputCost} title="Output cost" />}
            {typeof trace.totalCost === 'number' && <CostChip cost={trace.totalCost} title="Total cost" />}
        </header>
    )
}

function TraceSidebar({ trace, eventId }: { trace: LLMTrace; eventId?: string | null }): JSX.Element {
    return (
        <aside className="border-border h-80 bg-bg-light border rounded overflow-hidden md:h-full md:w-72">
            <header className="p-2">
                <h2 className="font-medium text-base p-0 m-0">Timeline</h2>
            </header>
            <LemonDivider className="m-0" />
            <ul className="overflow-y-auto h-full">
                {trace.events.map((event, index) => {
                    const usage = formatLLMUsage(event)
                    const eventSelected = eventId ? eventId === event.id : index === 0
                    return (
                        <li key={event.id} className="border-b border-border">
                            <Link
                                to={urls.llmObservabilityTrace(trace.id, {
                                    event: event.id,
                                    timestamp: trace.createdAt,
                                })}
                                className={classNames(
                                    'flex flex-col gap-1 p-2 text-xs hover:bg-primary-highlight',
                                    eventSelected && 'bg-primary-highlight'
                                )}
                            >
                                <div className="flex flex-row flex-wrap items-center">
                                    <LemonTag className="mr-2">Generation</LemonTag> {event.properties.$ai_model} (
                                    {event.properties.$ai_provider})
                                </div>
                                <div className="flex flex-row flex-wrap text-muted items-center gap-2">
                                    <LemonTag type="muted">{formatLLMLatency(event.properties.$ai_latency)}</LemonTag>
                                    {usage && <span>{usage}</span>}
                                    {event.properties.$ai_total_cost_usd && (
                                        <span>{formatLLMCost(event.properties.$ai_total_cost_usd)}</span>
                                    )}
                                </div>
                            </Link>
                        </li>
                    )
                })}
            </ul>
        </aside>
    )
}

function EventContent({ event }: { event?: LLMTraceEvent | null }): JSX.Element {
    return (
        <div className="flex-1 bg-bg-light border rounded flex flex-col border-border p-4 overflow-y-auto">
            {!event ? (
                <InsightEmptyState heading="Event not found" detail="Check if the event ID is correct." />
            ) : (
                <>
                    <header>
                        <div className="flex-row flex items-center gap-2 mb-4">
                            <LemonTag type="muted">Generation</LemonTag>
                            <h3 className="text-lg font-medium p-0 m-0">
                                {event.properties.$ai_model} ({event.properties.$ai_provider})
                            </h3>
                        </div>
                        <MetadataHeader eventProperties={event.properties} className="mb-2" />
                        <ParametersHeader eventProperties={event.properties} />
                    </header>
                    <LemonDivider className="my-4" />
                    <ConversationMessagesDisplay eventProperties={event.properties} />
                </>
            )}
        </div>
    )
}
