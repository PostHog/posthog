import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconAIText, IconCopy } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EventContent, TraceMetadata, TraceSidebar } from './LLMAnalyticsTraceScene'
import { EnrichedTraceTreeNode, llmAnalyticsTraceDataLogic } from './llmAnalyticsTraceDataLogic'
import { llmAnalyticsTraceDebugLogic } from './llmAnalyticsTraceDebugLogic'
import { llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'

export const scene: SceneExport = {
    component: LLMAnalyticsTraceDebugScene,
}

export function LLMAnalyticsTraceDebugScene(): JSX.Element {
    return <TraceDebugSceneContent />
}

function TraceDebugSceneContent(): JSX.Element {
    const { parsedTrace, parseError, isValidTrace } = useValues(llmAnalyticsTraceDebugLogic)
    const { setTraceJSON } = useActions(llmAnalyticsTraceDebugLogic)
    const [jsonInput, setJsonInput] = useState('')

    const handleParse = (): void => {
        setTraceJSON(jsonInput)
    }

    const handleLoadExample = (): void => {
        const exampleJSON = {
            trace_id: 'example-trace-abc123',
            name: 'Example Chat Completion',
            timestamp: new Date().toISOString(),
            total_cost: 0.0015,
            total_tokens: {
                input: 100,
                output: 50,
            },
            events: [
                {
                    type: 'generation',
                    name: 'Chat Completion',
                    model: 'gpt-4',
                    provider: 'openai',
                    messages: [
                        {
                            role: 'user',
                            content: 'What is the capital of France?',
                        },
                        {
                            role: 'assistant',
                            content: 'The capital of France is Paris.',
                        },
                    ],
                    metrics: {
                        latency: 1.234,
                        tokens: {
                            input: 100,
                            output: 50,
                        },
                        cost: 0.0015,
                    },
                },
            ],
        }
        const jsonString = JSON.stringify(exampleJSON, null, 2)
        setJsonInput(jsonString)
        setTraceJSON(jsonString)
    }

    return (
        <div className="flex flex-col gap-4 p-4">
            <header>
                <h1 className="text-2xl font-semibold mb-2 flex items-center gap-2">
                    <IconAIText />
                    LLM Analytics Trace Debug View
                </h1>
                <p className="text-muted">
                    Paste trace JSON (from "Copy trace JSON" button) to visualize and debug the trace structure
                </p>
            </header>

            <div className="flex flex-col gap-2">
                <div className="flex gap-2 items-center">
                    <LemonButton type="primary" onClick={handleParse} disabled={!jsonInput.trim()}>
                        Parse and render trace
                    </LemonButton>
                    <LemonButton type="secondary" onClick={handleLoadExample}>
                        Load example
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

                <LemonTextArea
                    placeholder="Paste your trace JSON here..."
                    value={jsonInput}
                    onChange={setJsonInput}
                    minRows={10}
                    className="font-mono text-xs"
                />

                {parseError && (
                    <div className="p-3 bg-danger-highlight border border-danger rounded">
                        <p className="font-semibold text-danger">Parse Error:</p>
                        <p className="text-sm text-danger">{parseError}</p>
                    </div>
                )}
            </div>

            {isValidTrace && parsedTrace && <TraceDebugRenderer trace={parsedTrace} />}
        </div>
    )
}

function TraceDebugRenderer({ trace }: { trace: any }): JSX.Element {
    // Convert the minimal export format to the full trace format
    const { mockTrace, mockTree } = convertMinimalTraceToFull(trace)

    // Create mock query
    const mockQuery = {
        kind: 'DataTableNode' as const,
        source: {
            kind: 'EventsQuery' as const,
        },
    }

    // Create mock cached results that simulate the API response
    const mockCachedResults = {
        results: [mockTrace],
        hasMore: false,
    }

    return (
        <div className="mt-4">
            <BindLogic logic={llmAnalyticsTraceLogic} props={{ traceId: mockTrace.id }}>
                <BindLogic
                    logic={llmAnalyticsTraceDataLogic}
                    props={{
                        traceId: mockTrace.id,
                        query: mockQuery,
                        cachedResults: mockCachedResults,
                        searchQuery: '',
                    }}
                >
                    <TraceDebugView trace={mockTrace} tree={mockTree} />
                </BindLogic>
            </BindLogic>
        </div>
    )
}

function TraceDebugView({ trace, tree }: { trace: LLMTrace; tree: EnrichedTraceTreeNode[] }): JSX.Element {
    const { eventId } = useValues(llmAnalyticsTraceLogic)
    const { event, searchQuery } = useValues(llmAnalyticsTraceDataLogic)

    return (
        <div className="relative flex flex-col gap-3 p-4 bg-surface-primary border rounded">
            <div className="p-2 bg-warning-highlight border border-warning rounded">
                <p className="text-sm font-semibold">Debug Mode</p>
                <p className="text-xs">
                    This is a preview rendering of the trace JSON. Some features may not work as expected in debug mode.
                </p>
            </div>

            <div className="flex items-start justify-between">
                <TraceMetadata trace={trace} metricEvents={[]} feedbackEvents={[]} />
            </div>

            <div className="flex flex-1 min-h-0 gap-3 flex-col md:flex-row">
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

    const llmEvent: LLMTraceEvent = {
        id: eventId,
        event: event.type === 'generation' ? '$ai_generation' : '$ai_span',
        createdAt: new Date().toISOString(),
        properties: {
            $ai_trace_id: traceId,
            $ai_generation_id: eventId,
            $ai_span_name: event.name,
            $ai_model: event.model,
            $ai_provider: event.provider,
            $ai_input: event.messages || event.input,
            $ai_output: event.messages?.[event.messages.length - 1] || event.output,
            $ai_output_choices: event.messages?.filter((m: any) => m.role === 'assistant'),
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
