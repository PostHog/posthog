import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconReceipt, IconUpload } from '@posthog/icons'
import { LemonButton, LemonTabs, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { TraceAggregationInfo } from './components/TraceAggregationInfo'
import { TraceConversationContent } from './components/TraceConversationContent'
import { TraceEventMetadata } from './components/TraceEventMetadata'
import { EventTypeTag, TraceSidebarBase } from './components/TraceSidebarBase'
import { ParametersHeader } from './ConversationDisplay/ParametersHeader'
import { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'
import { TraceViewMode } from './llmAnalyticsTraceLogic'
import { llmAnalyticsTracePreviewLogic } from './llmAnalyticsTracePreviewLogic'
import { findNodeByEventId } from './traceViewUtils'
import { formatLLMCost, formatLLMEventTitle, isLLMEvent } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsTracePreviewScene,
    logic: llmAnalyticsTracePreviewLogic,
}

export function LLMAnalyticsTracePreviewScene(): JSX.Element {
    const { hasTrace, trace, enrichedTree, event, validationError, effectiveEventId } =
        useValues(llmAnalyticsTracePreviewLogic)
    const { setSelectedEventId } = useActions(llmAnalyticsTracePreviewLogic)
    const [searchQuery, setSearchQuery] = useState('')
    const [viewMode, setViewMode] = useState<TraceViewMode>(TraceViewMode.Conversation)

    React.useEffect(() => {
        setSearchQuery('')
        setViewMode(TraceViewMode.Conversation)
    }, [trace?.id])

    return (
        <div className="min-h-screen bg-bg-3000 p-4">
            <div className="max-w-7xl mx-auto">
                <header className="mb-6">
                    <h1 className="text-2xl font-bold mb-2">LLM trace preview</h1>
                    {!hasTrace && <p className="text-muted">Paste the exported LLM trace JSON to preview it.</p>}
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
                            <PreviewTraceSidebar
                                trace={trace}
                                eventId={effectiveEventId}
                                tree={enrichedTree}
                                searchQuery={searchQuery}
                                onSearchChange={setSearchQuery}
                                onSelectEvent={setSelectedEventId}
                            />
                            <PreviewEventContent
                                event={event}
                                tree={enrichedTree}
                                searchQuery={searchQuery}
                                viewMode={viewMode}
                                onViewModeChange={setViewMode}
                            />
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    )
}

function TraceInputArea({ validationError }: { validationError: string | null }): JSX.Element {
    const { rawJson } = useValues(llmAnalyticsTracePreviewLogic)
    const { setRawJson, setValidationError, parseAndLoadTrace } = useActions(llmAnalyticsTracePreviewLogic)
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

            reader.onerror = (): void => {
                setValidationError('Failed to read file. Please try again.')
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
    searchQuery,
    onSearchChange,
    onSelectEvent,
}: {
    trace: LLMTrace
    eventId?: string | null
    tree: EnrichedTraceTreeNode[]
    searchQuery: string
    onSearchChange: (searchQuery: string) => void
    onSelectEvent: (eventId: string) => void
}): JSX.Element {
    return (
        <TraceSidebarBase
            trace={trace}
            tree={tree}
            selectedEventId={eventId}
            searchQuery={searchQuery}
            onSearchChange={onSearchChange}
            onSelectEvent={onSelectEvent}
            eventTypeExpanded={() => true}
        />
    )
}

function PreviewEventContent({
    event,
    tree,
    searchQuery,
    viewMode,
    onViewModeChange,
}: {
    event: LLMTrace | LLMTraceEvent | null
    tree: EnrichedTraceTreeNode[]
    searchQuery?: string
    viewMode: TraceViewMode
    onViewModeChange: (viewMode: TraceViewMode) => void
}): JSX.Element {
    if (!event) {
        return (
            <main className="flex-1 min-w-0 bg-surface-primary max-h-fit border border-primary rounded flex flex-col p-4 overflow-y-auto">
                <p className="text-muted">Select an event from the tree to view its details.</p>
            </main>
        )
    }

    const currentNode = findNodeByEventId(tree, event.id)
    const aggregation = currentNode?.aggregation

    return (
        <main className="flex-1 min-w-0 bg-surface-primary max-h-fit border border-primary rounded flex flex-col p-4 overflow-y-auto">
            <header className="space-y-2">
                <div className="flex-row flex items-center gap-2">
                    <EventTypeTag event={event} />
                    <h3 className="text-lg font-semibold p-0 m-0 truncate flex-1">{formatLLMEventTitle(event)}</h3>
                </div>
                <TraceEventMetadata event={event} />
                {isLLMEvent(event) && <ParametersHeader eventProperties={event.properties} />}
                {aggregation && <TraceAggregationInfo aggregation={aggregation} />}
            </header>
            <LemonTabs
                activeKey={viewMode}
                onChange={onViewModeChange}
                tabs={[
                    {
                        key: TraceViewMode.Conversation,
                        label: 'Conversation',
                        'data-attr': 'llma-trace-conversation-tab',
                        content: <TraceConversationContent event={event} searchQuery={searchQuery} />,
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
