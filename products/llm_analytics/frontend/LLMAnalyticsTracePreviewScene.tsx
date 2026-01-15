import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconReceipt, IconUpload } from '@posthog/icons'
import { LemonButton, LemonTabs, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { EventContentDisplayAsync, EventContentGeneration } from './components/EventContentWithAsyncData'
import { EventTypeTag, TraceSidebarBase } from './components/TraceSidebarBase'
import { EnrichedTraceTreeNode, SpanAggregation } from './llmAnalyticsTraceDataLogic'
import { TraceViewMode } from './llmAnalyticsTraceLogic'
import { llmAnalyticsTracePreviewLogic } from './llmAnalyticsTracePreviewLogic'
import { formatLLMCost, formatLLMEventTitle, formatLLMLatency, isLLMEvent } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsTracePreviewScene,
    logic: llmAnalyticsTracePreviewLogic,
}

export function LLMAnalyticsTracePreviewScene(): JSX.Element {
    const { hasTrace, trace, enrichedTree, event, searchQuery, validationError } =
        useValues(llmAnalyticsTracePreviewLogic)
    const { selectedEventId: eventId } = useValues(llmAnalyticsTracePreviewLogic)

    return (
        <div className="min-h-screen bg-bg-3000 p-4">
            <div className="max-w-7xl mx-auto">
                <header className="mb-6">
                    <h1 className="text-2xl font-bold mb-2">LLM trace preview</h1>
                    <p className="text-muted">Paste the exported LLM trace JSON to preview it.</p>
                </header>

                {!hasTrace ? (
                    <TraceInputArea validationError={validationError} />
                ) : trace ? (
                    <div className="flex flex-col gap-3">
                        <div className="flex items-start justify-between">
                            <PreviewTraceMetadata trace={trace} />
                            <ClearTraceButton />
                        </div>
                        <div className="flex flex-1 min-h-0 gap-3 flex-col md:flex-row">
                            <PreviewTraceSidebar trace={trace} eventId={eventId} tree={enrichedTree} />
                            <PreviewEventContent event={event} tree={enrichedTree} searchQuery={searchQuery} />
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    )
}

function TraceInputArea({ validationError }: { validationError: string | null }): JSX.Element {
    const { rawJson } = useValues(llmAnalyticsTracePreviewLogic)
    const { setRawJson, parseAndLoadTrace } = useActions(llmAnalyticsTracePreviewLogic)
    const [isDragOver, setIsDragOver] = useState(false)

    const handleDragOver = (e: React.DragEvent): void => {
        e.preventDefault()
        setIsDragOver(true)
    }

    const handleDragLeave = (): void => {
        setIsDragOver(false)
    }

    const handleDrop = (e: React.DragEvent): void => {
        e.preventDefault()
        setIsDragOver(false)

        const file = e.dataTransfer.files[0]

        if (file && file.type === 'application/json') {
            const reader = new FileReader()

            reader.onload = (event): void => {
                const content = event.target?.result

                if (typeof content === 'string') {
                    setRawJson(content)
                }
            }
            reader.readAsText(file)
        }
    }

    const handleLoadTrace = (): void => {
        parseAndLoadTrace()
    }

    return (
        <div
            className={clsx(
                'border-2 border-dashed rounded-lg p-6 transition-colors',
                isDragOver ? 'border-primary bg-primary-highlight' : 'border-border'
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
        >
            <div className="flex flex-col items-center gap-4 mb-4">
                <IconUpload className="w-12 h-12 text-muted" />
                <p className="text-muted text-center">Drag and drop a JSON file here, or paste the trace JSON below</p>
            </div>

            <LemonTextArea
                placeholder='Paste your trace JSON here... (e.g., {"trace_id": "...", "events": [...]})'
                value={rawJson}
                onChange={setRawJson}
                minRows={10}
                maxRows={20}
                className="font-mono text-sm"
                data-attr="trace-json-input"
            />

            {validationError && (
                <div className="mt-2 p-2 bg-danger-highlight text-danger rounded">
                    <strong>Error:</strong> {validationError}
                </div>
            )}

            <div className="mt-4 flex justify-end">
                <LemonButton
                    type="primary"
                    onClick={handleLoadTrace}
                    disabled={!rawJson.trim()}
                    data-attr="load-trace-button"
                >
                    Load trace
                </LemonButton>
            </div>
        </div>
    )
}

function ClearTraceButton(): JSX.Element {
    const { clearTrace } = useActions(llmAnalyticsTracePreviewLogic)

    return (
        <LemonButton type="secondary" size="small" onClick={clearTrace} data-attr="clear-trace-button">
            Clear and load new trace
        </LemonButton>
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

function PreviewTraceMetadata({ trace }: { trace: LLMTrace }): JSX.Element {
    return (
        <header className="flex gap-1.5 flex-wrap">
            {trace.traceName && (
                <Chip title="Trace name">
                    <span className="font-medium">{trace.traceName}</span>
                </Chip>
            )}
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
        </header>
    )
}

function PreviewTraceSidebar({
    trace,
    eventId,
    tree,
}: {
    trace: LLMTrace
    eventId?: string | null
    tree: EnrichedTraceTreeNode[]
}): JSX.Element {
    const { searchQuery, eventTypeExpanded } = useValues(llmAnalyticsTracePreviewLogic)
    const { setSearchQuery, setSelectedEventId } = useActions(llmAnalyticsTracePreviewLogic)

    return (
        <TraceSidebarBase
            trace={trace}
            tree={tree}
            selectedEventId={eventId}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onSelectEvent={setSelectedEventId}
            eventTypeExpanded={eventTypeExpanded}
        />
    )
}

function PreviewEventContent({
    event,
    tree,
    searchQuery,
}: {
    event: LLMTrace | LLMTraceEvent | null
    tree: EnrichedTraceTreeNode[]
    searchQuery?: string
}): JSX.Element {
    const { viewMode } = useValues(llmAnalyticsTracePreviewLogic)
    const { setViewMode } = useActions(llmAnalyticsTracePreviewLogic)

    if (!event) {
        return (
            <main className="flex-1 min-w-0 bg-surface-primary max-h-fit border border-primary rounded flex flex-col p-4 overflow-y-auto">
                <p className="text-muted">Select an event from the tree to view its details.</p>
            </main>
        )
    }

    const currentNode = findNode(tree, event.id)
    const aggregation = currentNode?.aggregation

    return (
        <main className="flex-1 min-w-0 bg-surface-primary max-h-fit border border-primary rounded flex flex-col p-4 overflow-y-auto">
            <header className="deprecated-space-y-2">
                <div className="flex-row flex items-center gap-2">
                    <EventTypeTag event={event} />
                    <h3 className="text-lg font-semibold p-0 m-0 truncate flex-1">{formatLLMEventTitle(event)}</h3>
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
                {aggregation && <AggregationInfo aggregation={aggregation} />}
            </header>
            <LemonTabs
                activeKey={viewMode}
                onChange={setViewMode}
                tabs={[
                    {
                        key: TraceViewMode.Conversation,
                        label: 'Conversation',
                        'data-attr': 'llma-trace-conversation-tab',
                        content: <ConversationTabContent event={event} searchQuery={searchQuery} />,
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
                ]}
            />
        </main>
    )
}

function AggregationInfo({ aggregation }: { aggregation: SpanAggregation }): JSX.Element {
    return (
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
    )
}

function ConversationTabContent({
    event,
    searchQuery,
}: {
    event: LLMTrace | LLMTraceEvent
    searchQuery?: string
}): JSX.Element {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_generation') {
            return (
                <EventContentGeneration
                    eventId={event.id}
                    rawInput={event.properties.$ai_input}
                    rawOutput={event.properties.$ai_output_choices ?? event.properties.$ai_output}
                    tools={event.properties.$ai_tools}
                    errorData={event.properties.$ai_error}
                    httpStatus={event.properties.$ai_http_status}
                    raisedError={event.properties.$ai_is_error}
                    searchQuery={searchQuery}
                />
            )
        }

        if (event.event === '$ai_embedding') {
            return (
                <EventContentDisplayAsync
                    eventId={event.id}
                    rawInput={event.properties.$ai_input}
                    rawOutput="Embedding vector generated"
                />
            )
        }

        return (
            <EventContentDisplayAsync
                eventId={event.id}
                rawInput={event.properties.$ai_input_state}
                rawOutput={event.properties.$ai_output_state ?? event.properties.$ai_error}
                raisedError={event.properties.$ai_is_error}
            />
        )
    }

    return <EventContentDisplayAsync eventId={event.id} rawInput={event.inputState} rawOutput={event.outputState} />
}

function findNode(tree: EnrichedTraceTreeNode[], eventId: string): EnrichedTraceTreeNode | null {
    for (const node of tree) {
        if (node.event.id === eventId) {
            return node
        }

        if (node.children) {
            const found = findNode(node.children, eventId)

            if (found) {
                return found
            }
        }
    }

    return null
}
