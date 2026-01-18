import { MinimalTraceExport, parseTraceExportJson, validateTraceExport } from './traceImportUtils'

describe('traceImportUtils', () => {
    describe('validateTraceExport', () => {
        describe('invalid input types', () => {
            it.each([
                [null, 'Invalid JSON structure: expected an object'],
                [undefined, 'Invalid JSON structure: expected an object'],
                ['string', 'Invalid JSON structure: expected an object'],
                [123, 'Invalid JSON structure: expected an object'],
            ])('returns error for %p', (input, expectedError) => {
                const result = validateTraceExport(input)
                expect(result.valid).toBe(false)
                expect(result.error).toBe(expectedError)
            })

            it('returns error for empty array (treated as object without trace_id)', () => {
                const result = validateTraceExport([])
                expect(result.valid).toBe(false)
                expect(result.error).toBe('Missing or invalid trace_id')
            })
        })

        describe('trace_id validation', () => {
            it.each([
                [
                    { timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid trace_id',
                ],
                [
                    { trace_id: null, timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid trace_id',
                ],
                [
                    { trace_id: 123, timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid trace_id',
                ],
                [
                    { trace_id: '', timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid trace_id',
                ],
            ])('returns error for invalid trace_id: %p', (input, expectedError) => {
                const result = validateTraceExport(input)
                expect(result.valid).toBe(false)
                expect(result.error).toBe(expectedError)
            })
        })

        describe('timestamp validation', () => {
            it.each([
                [{ trace_id: 'test-123', events: [{ type: 'span', name: 'test' }] }, 'Missing or invalid timestamp'],
                [
                    { trace_id: 'test-123', timestamp: null, events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid timestamp',
                ],
                [
                    { trace_id: 'test-123', timestamp: 123, events: [{ type: 'span', name: 'test' }] },
                    'Missing or invalid timestamp',
                ],
            ])('returns error for invalid timestamp: %p', (input, expectedError) => {
                const result = validateTraceExport(input)
                expect(result.valid).toBe(false)
                expect(result.error).toBe(expectedError)
            })
        })

        describe('events array validation', () => {
            it.each([
                [{ trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z' }, 'Missing or invalid events array'],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: null },
                    'Missing or invalid events array',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: 'not-an-array' },
                    'Missing or invalid events array',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: {} },
                    'Missing or invalid events array',
                ],
            ])('returns error for invalid events: %p', (input, expectedError) => {
                const result = validateTraceExport(input)
                expect(result.valid).toBe(false)
                expect(result.error).toBe(expectedError)
            })

            it('returns error for empty events array', () => {
                const result = validateTraceExport({
                    trace_id: 'test-123',
                    timestamp: '2024-01-01T12:00:00Z',
                    events: [],
                })
                expect(result.valid).toBe(false)
                expect(result.error).toBe('Events array is empty')
            })
        })

        describe('individual event validation', () => {
            it.each([
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: [null] },
                    'Invalid event in events array',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: ['string-event'] },
                    'Invalid event in events array',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: [{ name: 'test' }] },
                    'Event missing required type field',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: [{ type: 123, name: 'test' }] },
                    'Event missing required type field',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span' }] },
                    'Event missing required name field',
                ],
                [
                    { trace_id: 'test-123', timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 123 }] },
                    'Event missing required name field',
                ],
            ])('returns error for invalid event: %p', (input, expectedError) => {
                const result = validateTraceExport(input)
                expect(result.valid).toBe(false)
                expect(result.error).toBe(expectedError)
            })
        })

        describe('valid inputs', () => {
            it('accepts minimal valid trace', () => {
                const result = validateTraceExport({
                    trace_id: 'test-123',
                    timestamp: '2024-01-01T12:00:00Z',
                    events: [{ type: 'span', name: 'test' }],
                })
                expect(result.valid).toBe(true)
                expect(result.error).toBeUndefined()
            })

            it('accepts trace with optional fields', () => {
                const result = validateTraceExport({
                    trace_id: 'test-123',
                    name: 'My Trace',
                    timestamp: '2024-01-01T12:00:00Z',
                    total_cost: 0.05,
                    total_tokens: { input: 100, output: 50 },
                    events: [{ type: 'generation', name: 'GPT-4 call', model: 'gpt-4' }],
                })
                expect(result.valid).toBe(true)
            })

            it('accepts trace with multiple events', () => {
                const result = validateTraceExport({
                    trace_id: 'test-123',
                    timestamp: '2024-01-01T12:00:00Z',
                    events: [
                        { type: 'span', name: 'root' },
                        { type: 'generation', name: 'llm-call' },
                        { type: 'embedding', name: 'embed-text' },
                    ],
                })
                expect(result.valid).toBe(true)
            })
        })
    })

    describe('parseTraceExportJson', () => {
        const createMinimalTrace = (overrides: Partial<MinimalTraceExport> = {}): MinimalTraceExport => ({
            trace_id: 'test-trace-123',
            timestamp: '2024-01-01T12:00:00Z',
            events: [{ type: 'generation', name: 'Test Generation' }],
            ...overrides,
        })

        describe('JSON parsing errors', () => {
            it('throws error for empty string', () => {
                expect(() => parseTraceExportJson('')).toThrow('Invalid JSON format')
            })

            it('throws error for whitespace-only string', () => {
                expect(() => parseTraceExportJson('   ')).toThrow('Invalid JSON format')
            })

            it('throws error for invalid JSON syntax', () => {
                expect(() => parseTraceExportJson('{ invalid json }')).toThrow('Invalid JSON format')
            })

            it('throws error for unclosed brackets', () => {
                expect(() => parseTraceExportJson('{ "trace_id": "123"')).toThrow('Invalid JSON format')
            })
        })

        describe('generation event conversion', () => {
            it('converts basic generation event', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'GPT-4 Call' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events).toHaveLength(1)
                expect(result.trace.events[0].event).toBe('$ai_generation')
                expect(result.trace.events[0].properties.$ai_span_name).toBe('GPT-4 Call')
                expect(result.trace.events[0].properties.$ai_generation_id).not.toBeUndefined()
            })

            it('converts generation with model and provider', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'LLM Call', model: 'gpt-4', provider: 'openai' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_model).toBe('gpt-4')
                expect(result.trace.events[0].properties.$ai_provider).toBe('openai')
            })

            it('converts generation with messages to input/output', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'generation',
                            name: 'Chat',
                            messages: [
                                { role: 'system', content: 'You are helpful' },
                                { role: 'user', content: 'Hello' },
                                { role: 'assistant', content: 'Hi there!' },
                            ],
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_input).toEqual([
                    { role: 'system', content: 'You are helpful' },
                    { role: 'user', content: 'Hello' },
                ])
                expect(result.trace.events[0].properties.$ai_output_choices).toEqual([
                    { role: 'assistant', content: 'Hi there!' },
                ])
            })

            it('converts generation with tools', () => {
                const tools = [{ name: 'get_weather', description: 'Get weather info' }]
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'Tool Call', available_tools: tools }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_tools).toEqual(tools)
            })

            it('converts generation with full metrics', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'generation',
                            name: 'Metered Call',
                            metrics: {
                                latency: 500,
                                tokens: { input: 100, output: 50 },
                                cost: 0.002,
                            },
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_latency).toBe(500)
                expect(result.trace.events[0].properties.$ai_input_tokens).toBe(100)
                expect(result.trace.events[0].properties.$ai_output_tokens).toBe(50)
                expect(result.trace.events[0].properties.$ai_total_cost_usd).toBe(0.002)
            })
        })

        describe('embedding event conversion', () => {
            it('converts basic embedding event', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'embedding', name: 'Embed Text' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].event).toBe('$ai_embedding')
                expect(result.trace.events[0].properties.$ai_embedding_id).not.toBeUndefined()
            })

            it('converts embedding with model', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'embedding', name: 'Embed', model: 'text-embedding-3-small', provider: 'openai' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_model).toBe('text-embedding-3-small')
                expect(result.trace.events[0].properties.$ai_provider).toBe('openai')
            })

            it('converts embedding with input', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'embedding', name: 'Embed', input: 'Text to embed' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_input).toBe('Text to embed')
            })
        })

        describe('span event conversion', () => {
            it('converts basic span event', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'span', name: 'Process Data' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].event).toBe('$ai_span')
                expect(result.trace.events[0].properties.$ai_span_id).not.toBeUndefined()
            })

            it('converts span with input/output states', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'span',
                            name: 'Transform',
                            input: { query: 'test query' },
                            output: { result: 'test result' },
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_input_state).toEqual({ query: 'test query' })
                expect(result.trace.events[0].properties.$ai_output_state).toEqual({ result: 'test result' })
            })

            it('converts trace type as span', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'trace', name: 'Root Trace' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].event).toBe('$ai_span')
            })
        })

        describe('error handling in events', () => {
            it('converts string error', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'Failed Call', error: 'API rate limit exceeded' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_is_error).toBe(true)
                expect(result.trace.events[0].properties.$ai_error).toBe('API rate limit exceeded')
            })

            it('converts object error', () => {
                const errorObj = { message: 'Rate limit', code: 429 }
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'Failed Call', error: errorObj }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_is_error).toBe(true)
                expect(result.trace.events[0].properties.$ai_error).toEqual(errorObj)
            })

            it('filters placeholder error message', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'generation',
                            name: 'Error Event',
                            error: 'Error occurred (details not available)',
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_is_error).toBe(true)
                expect(result.trace.events[0].properties.$ai_error).toBeUndefined()
            })
        })

        describe('metrics handling', () => {
            it('handles full metrics', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'span',
                            name: 'Span',
                            metrics: {
                                latency: 1000,
                                tokens: { input: 200, output: 100 },
                                cost: 0.01,
                            },
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_latency).toBe(1000)
                expect(result.trace.events[0].properties.$ai_input_tokens).toBe(200)
                expect(result.trace.events[0].properties.$ai_output_tokens).toBe(100)
                expect(result.trace.events[0].properties.$ai_total_cost_usd).toBe(0.01)
            })

            it('handles partial metrics - latency only', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'span', name: 'Span', metrics: { latency: 500 } }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_latency).toBe(500)
                expect(result.trace.events[0].properties.$ai_input_tokens).toBeUndefined()
                expect(result.trace.events[0].properties.$ai_output_tokens).toBeUndefined()
                expect(result.trace.events[0].properties.$ai_total_cost_usd).toBeUndefined()
            })

            it('handles no metrics', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'span', name: 'Span' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].properties.$ai_latency).toBeUndefined()
                expect(result.trace.events[0].properties.$ai_input_tokens).toBeUndefined()
            })
        })

        describe('nested children', () => {
            it('converts single level of children', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'span',
                            name: 'Parent',
                            children: [{ type: 'generation', name: 'Child' }],
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events).toHaveLength(2)

                const parentEvent = result.trace.events[0]
                const childEvent = result.trace.events[1]
                expect(childEvent.properties.$ai_parent_id).toBe(parentEvent.id)
            })

            it('converts multi-level nesting', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'span',
                            name: 'Root',
                            children: [
                                {
                                    type: 'span',
                                    name: 'Level 1',
                                    children: [{ type: 'generation', name: 'Level 2' }],
                                },
                            ],
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events).toHaveLength(3)

                const rootEvent = result.trace.events[0]
                const level1Event = result.trace.events[1]
                const level2Event = result.trace.events[2]

                expect(level1Event.properties.$ai_parent_id).toBe(rootEvent.id)
                expect(level2Event.properties.$ai_parent_id).toBe(level1Event.id)
            })

            it('converts multiple children at same level', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'span',
                            name: 'Parent',
                            children: [
                                { type: 'generation', name: 'Child 1' },
                                { type: 'generation', name: 'Child 2' },
                            ],
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events).toHaveLength(3)

                const parentEvent = result.trace.events[0]
                const child1Event = result.trace.events[1]
                const child2Event = result.trace.events[2]

                expect(child1Event.properties.$ai_parent_id).toBe(parentEvent.id)
                expect(child2Event.properties.$ai_parent_id).toBe(parentEvent.id)
            })
        })

        describe('trace object structure', () => {
            it('builds trace with correct id and timestamp', () => {
                const trace = createMinimalTrace({
                    trace_id: 'my-trace-id',
                    timestamp: '2024-06-15T10:30:00Z',
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.id).toBe('my-trace-id')
                expect(result.trace.createdAt).toBe('2024-06-15T10:30:00Z')
            })

            it('builds trace with placeholder person', () => {
                const trace = createMinimalTrace()
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.person.uuid).toBe('preview-person')
                expect(result.trace.person.distinct_id).toBe('Preview User')
            })

            it('builds trace with token counts from total_tokens', () => {
                const trace = createMinimalTrace({
                    total_tokens: { input: 500, output: 200 },
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.inputTokens).toBe(500)
                expect(result.trace.outputTokens).toBe(200)
            })

            it('defaults token counts to 0 when not provided', () => {
                const trace = createMinimalTrace()
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.inputTokens).toBe(0)
                expect(result.trace.outputTokens).toBe(0)
            })

            it('includes total_cost in trace', () => {
                const trace = createMinimalTrace({
                    total_cost: 0.05,
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.totalCost).toBe(0.05)
            })

            it('includes trace name', () => {
                const trace = createMinimalTrace({
                    name: 'My Custom Trace',
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.traceName).toBe('My Custom Trace')
            })
        })

        describe('enriched tree structure', () => {
            it('returns enriched tree with display fields', () => {
                const trace = createMinimalTrace({
                    events: [
                        {
                            type: 'generation',
                            name: 'Call',
                            metrics: { latency: 500, tokens: { input: 100, output: 50 }, cost: 0.002 },
                        },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.enrichedTree).toHaveLength(1)
                expect(result.enrichedTree[0].displayLatency).not.toBeUndefined()
                expect(result.enrichedTree[0].displayTotalCost).not.toBeUndefined()
                expect(result.enrichedTree[0].displayUsage).not.toBeUndefined()
            })

            it('enriched tree has correct event reference', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'generation', name: 'Test Event' }],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.enrichedTree[0].event.properties.$ai_span_name).toBe('Test Event')
            })
        })

        describe('event ID generation', () => {
            it('generates sequential event IDs', () => {
                const trace = createMinimalTrace({
                    events: [
                        { type: 'span', name: 'First' },
                        { type: 'span', name: 'Second' },
                        { type: 'span', name: 'Third' },
                    ],
                })
                const result = parseTraceExportJson(JSON.stringify(trace))

                expect(result.trace.events[0].id).toBe('preview-event-1')
                expect(result.trace.events[1].id).toBe('preview-event-2')
                expect(result.trace.events[2].id).toBe('preview-event-3')
            })

            it('resets event IDs between parse calls', () => {
                const trace = createMinimalTrace({
                    events: [{ type: 'span', name: 'Event' }],
                })

                const result1 = parseTraceExportJson(JSON.stringify(trace))
                const result2 = parseTraceExportJson(JSON.stringify(trace))

                expect(result1.trace.events[0].id).toBe('preview-event-1')
                expect(result2.trace.events[0].id).toBe('preview-event-1')
            })
        })

        describe('validation integration', () => {
            it('throws validation error for missing trace_id', () => {
                const invalidTrace = { timestamp: '2024-01-01T12:00:00Z', events: [{ type: 'span', name: 'test' }] }
                expect(() => parseTraceExportJson(JSON.stringify(invalidTrace))).toThrow('Missing or invalid trace_id')
            })

            it('throws validation error for empty events', () => {
                const invalidTrace = { trace_id: 'test', timestamp: '2024-01-01T12:00:00Z', events: [] }
                expect(() => parseTraceExportJson(JSON.stringify(invalidTrace))).toThrow('Events array is empty')
            })
        })
    })
})
