import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EventContent, TraceMetadata, TraceSidebar } from './LLMAnalyticsTraceScene'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { llmAnalyticsTraceDebugLogic } from './llmAnalyticsTraceDebugLogic'
import { llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'

export function openLLMAnalyticsTraceDebugModal(): void {
    LemonDialog.open({
        title: 'LLM Analytics Trace Debug View',
        content: <TraceDebugModalContent />,
        primaryButton: null,
        width: 1400,
        inline: true,
    })
}

function TraceDebugModalContent(): JSX.Element {
    const { parsedTrace, parseError, isValidTrace, traceFormat } = useValues(llmAnalyticsTraceDebugLogic)
    const { setTraceJSON } = useActions(llmAnalyticsTraceDebugLogic)
    const [jsonInput, setJsonInput] = useState('')
    const [renderKey, setRenderKey] = useState(0)

    const handleParse = (): void => {
        setTraceJSON(jsonInput)
        // Force a re-render by incrementing the key
        setRenderKey((prev) => {
            return prev + 1
        })
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="text-muted text-sm">
                Paste trace JSON (from "Copy trace JSON" button) to visualize and debug the trace structure
            </div>

            <div className="flex flex-col gap-2">
                <LemonTextArea
                    placeholder="Paste your trace JSON here and click 'Render trace' to visualize..."
                    value={jsonInput}
                    onChange={setJsonInput}
                    minRows={8}
                    maxRows={12}
                    className="font-mono text-xs"
                />

                <div className="flex gap-2 items-center">
                    <LemonButton type="primary" onClick={handleParse} disabled={!jsonInput.trim()}>
                        {isValidTrace ? 'Re-render trace' : 'Render trace'}
                    </LemonButton>
                    {isValidTrace && parsedTrace && (
                        <LemonButton
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => copyToClipboard(JSON.stringify(parsedTrace, null, 2), 'formatted trace')}
                        >
                            Copy formatted
                        </LemonButton>
                    )}
                </div>

                {parseError && (
                    <div className="p-3 bg-danger-highlight border border-danger rounded">
                        <p className="font-semibold text-danger">Parse Error:</p>
                        <p className="text-sm text-danger">{parseError}</p>
                    </div>
                )}
            </div>

            {isValidTrace && parsedTrace && (
                <>
                    {traceFormat && (
                        <div className="p-2 bg-accent-highlight border border-border rounded text-xs">
                            <strong>Format detected:</strong>{' '}
                            {traceFormat === 'internal'
                                ? 'Internal trace format (raw $ai_ properties) - no conversion needed ✓'
                                : 'Export trace format (from Copy trace JSON button) - converting to internal format'}
                        </div>
                    )}
                    <TraceDebugRenderer key={renderKey} trace={parsedTrace} format={traceFormat} />
                </>
            )}
        </div>
    )
}

function TraceDebugRenderer({ trace, format }: { trace: any; format: 'internal' | 'export' | null }): JSX.Element {
    // Use internal format directly if available, otherwise convert from export format
    const { mockTrace, mockTree } =
        format === 'internal'
            ? { mockTrace: trace, mockTree: convertInternalEventsToTree(trace.events) }
            : convertMinimalTraceToFull(trace)

    // Make the traceId unique for each parse to force new logic instances
    const uniqueTraceId = `${mockTrace.id}-debug-${trace._parseTimestamp || Date.now()}`
    const traceWithUniqueId = { ...mockTrace, id: uniqueTraceId }

    // Create mock query
    const mockQuery = {
        kind: 'DataTableNode' as const,
        source: {
            kind: 'EventsQuery' as const,
        },
    }

    // Create mock cached results that simulate the API response
    const mockCachedResults = {
        results: [traceWithUniqueId],
        hasMore: false,
    }

    return (
        <div className="mt-4">
            <BindLogic logic={llmAnalyticsTraceLogic} props={{ traceId: uniqueTraceId, debugMode: true }}>
                <BindLogic
                    logic={llmAnalyticsTraceDataLogic}
                    props={{
                        traceId: uniqueTraceId,
                        query: mockQuery,
                        cachedResults: mockCachedResults,
                        searchQuery: '',
                    }}
                >
                    <TraceDebugView trace={traceWithUniqueId} tree={mockTree} />
                </BindLogic>
            </BindLogic>
        </div>
    )
}

function TraceDebugView({ trace, tree }: { trace: LLMTrace; tree: EnrichedTraceTreeNode[] }): JSX.Element {
    const { eventId } = useValues(llmAnalyticsTraceLogic)
    const { event, searchQuery } = useValues(llmAnalyticsTraceDataLogic)

    return (
        <div className="relative flex flex-col gap-3">
            <div className="p-2 bg-warning-highlight border border-warning rounded">
                <p className="text-sm font-semibold">Debug Mode</p>
                <p className="text-xs">
                    This is a preview rendering of the trace JSON. Some features may not work as expected in debug mode.
                </p>
            </div>

            <div className="flex items-start justify-between">
                <TraceMetadata trace={trace} metricEvents={[]} feedbackEvents={[]} />
            </div>

            <div className="flex flex-1 min-h-0 gap-3 flex-col md:flex-row" style={{ minHeight: '400px' }}>
                <TraceSidebar trace={trace} eventId={eventId} tree={tree} />
                <EventContent
                    trace={trace}
                    event={event || trace}
                    tree={tree}
                    searchQuery={searchQuery}
                    eventMetadata={{}}
                />
            </div>
        </div>
    )
}

// Convert internal format events directly to tree nodes (no conversion needed, just wrap in tree structure)
function convertInternalEventsToTree(events: LLMTraceEvent[]): EnrichedTraceTreeNode[] {
    return events.map((event) => ({
        event,
        displayTotalCost: event.properties.$ai_total_cost_usd || 0,
        displayLatency: event.properties.$ai_latency || 0,
        displayUsage:
            event.properties.$ai_input_tokens || event.properties.$ai_output_tokens
                ? `${event.properties.$ai_input_tokens || 0} → ${event.properties.$ai_output_tokens || 0}`
                : null,
        children: [], // Nested children would need to be built from parent/child relationships
    }))
}

function convertMinimalTraceToFull(minimalTrace: any): { mockTrace: LLMTrace; mockTree: EnrichedTraceTreeNode[] } {
    // Create the mock trace object
    const mockTrace: LLMTrace = {
        id: minimalTrace.trace_id || 'debug-trace',
        createdAt: minimalTrace.timestamp || new Date().toISOString(),
        traceName: minimalTrace.name,
        inputTokens: minimalTrace.total_tokens?.input || 0,
        outputTokens: minimalTrace.total_tokens?.output || 0,
        totalCost: minimalTrace.total_cost,
        totalLatency: 0,
    }

    // Convert events to enriched tree nodes
    const mockTree: EnrichedTraceTreeNode[] = (minimalTrace.events || []).map((event: any) =>
        convertEventToTreeNode(event, mockTrace.id)
    )

    return { mockTrace, mockTree }
}

function convertEventToTreeNode(event: any, traceId: string): EnrichedTraceTreeNode {
    const eventId = `${traceId}-event-${Math.random().toString(36).substring(7)}`
    const isGeneration = event.type === 'generation'

    // Reverse the export format back to the internal format
    // The export combines input/output messages into a single array (see buildEventExport in traceExportUtils.ts)
    // We need to split them back based on role
    let aiInput: any
    let aiOutput: any
    let aiOutputChoices: any

    if (isGeneration && event.messages) {
        // For generations: split messages by role (reverse of lines 68-82 in traceExportUtils.ts)
        aiInput = event.messages.filter((m: any) => m.role !== 'assistant')
        aiOutputChoices = event.messages.filter((m: any) => m.role === 'assistant')
    } else {
        // For spans: use raw input/output (reverse of lines 90-96 in traceExportUtils.ts)
        aiInput = event.input
        aiOutput = event.output
    }

    const llmEvent: LLMTraceEvent = {
        id: eventId,
        event: isGeneration ? '$ai_generation' : '$ai_span',
        createdAt: new Date().toISOString(),
        properties: {
            $ai_trace_id: traceId,
            $ai_generation_id: eventId,
            $ai_span_name: event.name,
            $ai_model: event.model,
            $ai_provider: event.provider,
            $ai_input: aiInput,
            $ai_output: aiOutput,
            $ai_output_choices: aiOutputChoices,
            $ai_input_state: event.input,
            $ai_output_state: event.output,
            $ai_tools: event.available_tools,
            $ai_error: event.error,
            $ai_is_error: !!event.error,
            $ai_latency: event.metrics?.latency,
            $ai_input_tokens: event.metrics?.tokens?.input,
            $ai_output_tokens: event.metrics?.tokens?.output,
            $ai_total_cost_usd: event.metrics?.cost,
        },
    }

    const node: EnrichedTraceTreeNode = {
        event: llmEvent,
        displayTotalCost: event.metrics?.cost || 0,
        displayLatency: event.metrics?.latency || 0,
        displayUsage: event.metrics?.tokens ? `${event.metrics.tokens.input} → ${event.metrics.tokens.output}` : null,
        children: event.children?.map((child: any) => convertEventToTreeNode(child, traceId)) || [],
    }

    return node
}
