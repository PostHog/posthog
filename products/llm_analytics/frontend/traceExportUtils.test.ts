import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'
import { buildMinimalTraceJSON } from './traceExportUtils'

describe('traceExportUtils', () => {
    const mockTrace: LLMTrace = {
        id: 'trace-123',
        createdAt: '2024-01-01T12:00:00Z',
        person: {
            uuid: 'person-123',
            created_at: '2024-01-01T00:00:00Z',
            properties: {},
            distinct_id: 'user-123',
        },
        totalLatency: 1500,
        inputTokens: 100,
        outputTokens: 50,
        totalCost: 0.005,
        traceName: 'Test Trace',
        events: [],
    }

    const mockGenerationEvent: LLMTraceEvent = {
        id: 'event-1',
        event: '$ai_generation',
        properties: {
            $ai_model: 'gpt-4',
            $ai_provider: 'openai',
            $ai_input: 'Hello, how are you?',
            $ai_output: 'I am doing well, thank you!',
            $ai_input_tokens: 5,
            $ai_output_tokens: 7,
            $ai_latency: 500,
            $ai_total_cost_usd: 0.002,
            $ai_tools: [
                {
                    name: 'get_weather',
                    description: 'Get the weather for a location',
                    parameters: { type: 'object' },
                },
            ],
        },
        createdAt: '2024-01-01T12:00:01Z',
    }

    const mockSpanEvent: LLMTraceEvent = {
        id: 'event-2',
        event: '$ai_span',
        properties: {
            $ai_input_state: { query: 'test query' },
            $ai_output_state: { result: 'test result' },
            $ai_latency: 200,
        },
        createdAt: '2024-01-01T12:00:02Z',
    }

    const mockErrorEvent: LLMTraceEvent = {
        id: 'event-3',
        event: '$ai_generation',
        properties: {
            $ai_model: 'gpt-3.5-turbo',
            $ai_provider: 'openai',
            $ai_input: 'This will fail',
            $ai_error: { message: 'API rate limit exceeded', code: 'rate_limit' },
            $ai_is_error: true,
        },
        createdAt: '2024-01-01T12:00:03Z',
    }

    describe('buildMinimalTraceJSON', () => {
        it('should build minimal trace with basic information', () => {
            const tree: EnrichedTraceTreeNode[] = []
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result).toEqual({
                trace_id: 'trace-123',
                name: 'Test Trace',
                timestamp: '2024-01-01T12:00:00Z',
                total_cost: 0.005,
                total_tokens: {
                    input: 100,
                    output: 50,
                },
                events: [],
            })
        })

        it('should handle trace without optional fields', () => {
            const minimalTrace: LLMTrace = {
                ...mockTrace,
                traceName: undefined,
                totalCost: undefined,
                inputTokens: undefined,
                outputTokens: undefined,
            }
            const tree: EnrichedTraceTreeNode[] = []
            const result = buildMinimalTraceJSON(minimalTrace, tree)

            expect(result).toEqual({
                trace_id: 'trace-123',
                timestamp: '2024-01-01T12:00:00Z',
                total_tokens: {
                    input: 0,
                    output: 0,
                },
                events: [],
            })
            expect(result.name).toBeUndefined()
            expect(result.total_cost).toBeUndefined()
        })

        it('should export generation events with messages and tools', () => {
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: mockGenerationEvent,
                    displayTotalCost: 0.002,
                    displayLatency: 500,
                    displayUsage: '5 → 7 tokens',
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events).toHaveLength(1)

            // Check the event structure
            expect(result.events[0].type).toBe('generation')
            expect(result.events[0].name).toContain('gpt-4')
            expect(result.events[0].model).toBe('gpt-4')
            expect(result.events[0].provider).toBe('openai')

            // Check messages array exactly
            expect(result.events[0].messages).toEqual([
                {
                    role: 'user',
                    content: 'Hello, how are you?',
                },
                {
                    role: 'assistant',
                    content: 'I am doing well, thank you!',
                },
            ])

            // Check available tools
            expect(result.events[0].available_tools).toEqual([
                {
                    name: 'get_weather',
                    description: 'Get the weather for a location',
                    parameters: { type: 'object' },
                },
            ])

            // Check metrics
            expect(result.events[0].metrics).toEqual({
                latency: 500,
                tokens: {
                    input: 5,
                    output: 7,
                },
                cost: 0.002,
            })
        })

        it('should export span events with input/output state', () => {
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: mockSpanEvent,
                    displayTotalCost: 0,
                    displayLatency: 200,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events).toHaveLength(1)
            expect(result.events[0]).toEqual({
                type: 'span',
                name: expect.any(String),
                input: { query: 'test query' },
                output: { result: 'test result' },
                metrics: {
                    latency: 200,
                },
            })
        })

        it('should handle error events', () => {
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: mockErrorEvent,
                    displayTotalCost: 0,
                    displayLatency: 0,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events).toHaveLength(1)
            expect(result.events[0]).toMatchObject({
                type: 'generation',
                name: expect.stringContaining('gpt-3.5-turbo'),
                model: 'gpt-3.5-turbo',
                provider: 'openai',
                error: { message: 'API rate limit exceeded', code: 'rate_limit' },
            })

            // Messages should still be present for error events
            expect(result.events[0].messages).toEqual([
                {
                    role: 'user',
                    content: 'This will fail',
                },
            ])
        })

        it('should handle error flag without error details', () => {
            const errorEvent: LLMTraceEvent = {
                ...mockSpanEvent,
                properties: {
                    ...mockSpanEvent.properties,
                    $ai_is_error: true,
                },
            }
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: errorEvent,
                    displayTotalCost: 0,
                    displayLatency: 200,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events[0].error).toBe('Error occurred (details not available)')
        })

        it('should handle nested events with children', () => {
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: mockSpanEvent,
                    displayTotalCost: 0,
                    displayLatency: 700,
                    displayUsage: null,
                    children: [
                        {
                            event: mockGenerationEvent,
                            displayTotalCost: 0.002,
                            displayLatency: 500,
                            displayUsage: '5 → 7 tokens',
                        },
                    ],
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events).toHaveLength(1)
            expect(result.events[0].children).toHaveLength(1)
            expect(result.events[0].children?.[0]).toMatchObject({
                type: 'generation',
                name: expect.stringContaining('gpt-4'),
                model: 'gpt-4',
            })
        })

        it('should handle events with only partial metrics', () => {
            const partialMetricsEvent: LLMTraceEvent = {
                id: 'event-4',
                event: '$ai_generation',
                properties: {
                    $ai_model: 'claude-3',
                    $ai_latency: 300,
                },
                createdAt: '2024-01-01T12:00:04Z',
            }
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: partialMetricsEvent,
                    displayTotalCost: 0,
                    displayLatency: 300,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events[0].metrics).toEqual({
                latency: 300,
            })
        })

        it('should handle events with no metrics', () => {
            const noMetricsEvent: LLMTraceEvent = {
                id: 'event-5',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T12:00:05Z',
            }
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: noMetricsEvent,
                    displayTotalCost: 0,
                    displayLatency: 0,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events[0].metrics).toBeUndefined()
        })

        it('should handle generation with output_choices instead of output', () => {
            const choicesEvent: LLMTraceEvent = {
                id: 'event-6',
                event: '$ai_generation',
                properties: {
                    $ai_model: 'gpt-4',
                    $ai_input: 'Question?',
                    $ai_output_choices: [
                        { message: { role: 'assistant', content: 'Answer 1' } },
                        { message: { role: 'assistant', content: 'Answer 2' } },
                    ],
                },
                createdAt: '2024-01-01T12:00:06Z',
            }
            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: choicesEvent,
                    displayTotalCost: 0,
                    displayLatency: 0,
                    displayUsage: null,
                },
            ]
            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events[0].messages).not.toBeUndefined()
            // The normalizeMessages function should handle the output_choices
            expect(result.events[0].messages?.length).toBeGreaterThanOrEqual(1)
        })

        it('should handle complex multi-level nesting', () => {
            const deepTree: EnrichedTraceTreeNode[] = [
                {
                    event: {
                        ...mockSpanEvent,
                        id: 'span-1',
                        properties: { ...mockSpanEvent.properties, name: 'root-span' },
                    },
                    displayTotalCost: 0,
                    displayLatency: 1000,
                    displayUsage: null,
                    children: [
                        {
                            event: {
                                ...mockSpanEvent,
                                id: 'span-2',
                                properties: { ...mockSpanEvent.properties, name: 'child-span' },
                            },
                            displayTotalCost: 0,
                            displayLatency: 500,
                            displayUsage: null,
                            children: [
                                {
                                    event: mockGenerationEvent,
                                    displayTotalCost: 0.002,
                                    displayLatency: 300,
                                    displayUsage: '5 → 7 tokens',
                                },
                            ],
                        },
                        {
                            event: { ...mockGenerationEvent, id: 'gen-2' },
                            displayTotalCost: 0.003,
                            displayLatency: 400,
                            displayUsage: '10 → 15 tokens',
                        },
                    ],
                },
            ]

            const result = buildMinimalTraceJSON(mockTrace, deepTree)

            expect(result.events).toHaveLength(1)
            expect(result.events[0].children).toHaveLength(2)
            expect(result.events[0].children?.[0].children).toHaveLength(1)
            expect(result.events[0].children?.[0].children?.[0].type).toBe('generation')
        })

        it('should handle messages with tool calls in generation events', () => {
            const toolCallEvent: LLMTraceEvent = {
                id: 'event-7',
                event: '$ai_generation',
                properties: {
                    $ai_model: 'gpt-4',
                    $ai_provider: 'openai',
                    $ai_input: [{ role: 'user', content: 'What is the weather?' }],
                    $ai_output: {
                        role: 'assistant',
                        content: null,
                        tool_calls: [
                            {
                                id: 'call_123',
                                type: 'function',
                                function: {
                                    name: 'get_weather',
                                    arguments: '{"location": "San Francisco"}',
                                },
                            },
                        ],
                    },
                },
                createdAt: '2024-01-01T12:00:07Z',
            }

            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: toolCallEvent,
                    displayTotalCost: 0,
                    displayLatency: 100,
                    displayUsage: null,
                },
            ]

            const result = buildMinimalTraceJSON(mockTrace, tree)

            expect(result.events[0].messages).not.toBeUndefined()
            expect(result.events[0].type).toBe('generation')

            // The messages array should contain both input and output messages
            expect(result.events[0].messages).toHaveLength(2)
            expect(result.events[0].messages?.[0]).toEqual({ role: 'user', content: 'What is the weather?' })

            // Check that the assistant message has tool_calls
            const assistantMessage = result.events[0].messages?.[1]
            expect(assistantMessage?.role).toBe('assistant')
            expect(assistantMessage?.tool_calls).not.toBeUndefined()
            expect(assistantMessage?.tool_calls).toHaveLength(1)
            expect(assistantMessage?.tool_calls?.[0]?.function?.name).toBe('get_weather')
        })

        it('should handle array inputs and outputs correctly', () => {
            const arrayInputEvent: LLMTraceEvent = {
                id: 'event-8',
                event: '$ai_generation',
                properties: {
                    $ai_model: 'gpt-4',
                    $ai_input: [
                        { role: 'system', content: 'You are a helpful assistant' },
                        { role: 'user', content: 'Hello' },
                    ],
                    $ai_output: [{ role: 'assistant', content: 'Hi there!' }],
                },
                createdAt: '2024-01-01T12:00:08Z',
            }

            const tree: EnrichedTraceTreeNode[] = [
                {
                    event: arrayInputEvent,
                    displayTotalCost: 0,
                    displayLatency: 50,
                    displayUsage: null,
                },
            ]

            const result = buildMinimalTraceJSON(mockTrace, tree)

            // Messages should be in exact order: input messages followed by output messages
            expect(result.events[0].messages).toEqual([
                { role: 'system', content: 'You are a helpful assistant' },
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
            ])
        })
    })
})
