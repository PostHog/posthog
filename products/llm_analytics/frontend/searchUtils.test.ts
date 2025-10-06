import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { findEventWithParents } from './llmAnalyticsTraceDataLogic'
import type { SearchMatch } from './searchUtils'
import {
    containsSearchQuery,
    eventMatchesSearch,
    extractAllText,
    findMessageOccurrences,
    findSearchMatches,
    findSearchOccurrences,
    findSidebarOccurrences,
    findTraceOccurrences,
} from './searchUtils'
import { normalizeMessages } from './utils'

describe('searchUtils', () => {
    describe('findSearchMatches', () => {
        const testCases: Array<[string, string, string, SearchMatch[]]> = [
            ['empty query returns empty array', 'test text', '', []],
            ['whitespace query returns empty array', 'test text', '  ', []],
            ['single match', 'hello world', 'world', [{ startIndex: 6, length: 5 }]],
            [
                'multiple matches',
                'test test test',
                'test',
                [
                    { startIndex: 0, length: 4 },
                    { startIndex: 5, length: 4 },
                    { startIndex: 10, length: 4 },
                ],
            ],
            ['case insensitive matching', 'Hello WORLD', 'world', [{ startIndex: 6, length: 5 }]],
            ['no matches returns empty array', 'hello world', 'xyz', []],
            ['match at start', 'test string', 'test', [{ startIndex: 0, length: 4 }]],
            ['match at end', 'string test', 'test', [{ startIndex: 7, length: 4 }]],
            ['special characters', 'test $special$ test', '$special$', [{ startIndex: 5, length: 9 }]],
            [
                'overlapping pattern',
                'aaaa',
                'aa',
                [
                    { startIndex: 0, length: 2 },
                    { startIndex: 2, length: 2 },
                ],
            ],
        ]

        test.each(testCases)('%s', (_testName, text, query, expected) => {
            expect(findSearchMatches(text, query)).toEqual(expected)
        })
    })

    describe('containsSearchQuery', () => {
        const testCases: Array<[string, string, string, boolean]> = [
            ['empty query returns false', 'test text', '', false],
            ['whitespace query returns false', 'test text', '  ', false],
            ['found returns true', 'hello world', 'world', true],
            ['not found returns false', 'hello world', 'xyz', false],
            ['case insensitive match', 'Hello WORLD', 'world', true],
            ['partial match returns true', 'testing', 'test', true],
            ['special characters match', 'test $special$', '$special$', true],
        ]

        test.each(testCases)('%s', (_testName, text, query, expected) => {
            expect(containsSearchQuery(text, query)).toBe(expected)
        })
    })

    describe('extractAllText', () => {
        it('extracts text from strings', () => {
            expect(extractAllText('hello world')).toBe('hello world')
        })

        it('converts numbers and booleans to strings', () => {
            expect(extractAllText(42)).toBe('42')
            expect(extractAllText(true)).toBe('true')
            expect(extractAllText(false)).toBe('false')
        })

        it('returns empty string for null/undefined', () => {
            expect(extractAllText(null)).toBe('')
            expect(extractAllText(undefined)).toBe('')
        })

        it('extracts text from flat objects', () => {
            const obj = { name: 'John', age: 30, active: true }
            expect(extractAllText(obj)).toBe('John 30 true')
        })

        it('extracts text from deeply nested objects', () => {
            const deepObj = {
                level1: {
                    level2: {
                        level3: {
                            level4: {
                                deepText: 'found it',
                                moreNesting: {
                                    level5: 'even deeper',
                                },
                            },
                        },
                    },
                },
            }
            const result = extractAllText(deepObj)
            expect(result).toContain('found it')
            expect(result).toContain('even deeper')
        })

        it('extracts text from arrays', () => {
            const arr = ['first', { nested: 'second' }, ['third', { deep: 'fourth' }]]
            const result = extractAllText(arr)
            expect(result).toContain('first')
            expect(result).toContain('second')
            expect(result).toContain('third')
            expect(result).toContain('fourth')
        })
    })

    describe('eventMatchesSearch', () => {
        const createEvent = (
            overrides: Record<string, any> = {}
        ): { properties: Record<string, any>; event?: string } => ({
            event: '$ai_generation',
            properties: {},
            ...overrides,
        })

        it('empty query matches everything', () => {
            expect(eventMatchesSearch(createEvent(), '')).toBe(true)
            expect(eventMatchesSearch(createEvent(), '  ')).toBe(true)
        })

        it('searches in event title (span name)', () => {
            const event = createEvent({
                properties: { $ai_span_name: 'My Test Span' },
            })
            expect(eventMatchesSearch(event, 'test')).toBe(true)
            expect(eventMatchesSearch(event, 'span')).toBe(true)
            expect(eventMatchesSearch(event, 'xyz')).toBe(false)
        })

        it('searches in event title (event name fallback)', () => {
            const event = createEvent({
                event: 'Custom Event Name',
                properties: {},
            })
            expect(eventMatchesSearch(event, 'custom')).toBe(true)
            expect(eventMatchesSearch(event, 'EVENT')).toBe(true)
        })

        it('searches in model name', () => {
            const event = createEvent({
                properties: { $ai_model: 'gpt-4-turbo' },
            })
            expect(eventMatchesSearch(event, 'gpt')).toBe(true)
            expect(eventMatchesSearch(event, 'TURBO')).toBe(true)
            expect(eventMatchesSearch(event, 'claude')).toBe(false)
        })

        it('searches in provider', () => {
            const event = createEvent({
                properties: { $ai_provider: 'OpenAI' },
            })
            expect(eventMatchesSearch(event, 'openai')).toBe(true)
            expect(eventMatchesSearch(event, 'OPENAI')).toBe(true)
            expect(eventMatchesSearch(event, 'anthropic')).toBe(false)
        })

        it('searches in tools', () => {
            const event = createEvent({
                properties: {
                    $ai_tools: [
                        { name: 'calculator', description: 'Performs math' },
                        { name: 'weather', description: 'Gets weather info' },
                    ],
                },
            })
            expect(eventMatchesSearch(event, 'calculator')).toBe(true)
            expect(eventMatchesSearch(event, 'math')).toBe(true)
            expect(eventMatchesSearch(event, 'weather')).toBe(true)
            expect(eventMatchesSearch(event, 'description')).toBe(true)
            expect(eventMatchesSearch(event, 'database')).toBe(false)
        })

        it('searches in input content', () => {
            const event = createEvent({
                properties: { $ai_input: 'What is the weather like?' },
            })
            expect(eventMatchesSearch(event, 'weather')).toBe(true)
            expect(eventMatchesSearch(event, 'WEATHER')).toBe(true)
        })

        it('searches in input state', () => {
            const event = createEvent({
                properties: { $ai_input_state: { message: 'test input state' } },
            })
            expect(eventMatchesSearch(event, 'input')).toBe(true)
            expect(eventMatchesSearch(event, 'state')).toBe(true)
        })

        it('searches in output content', () => {
            const event = createEvent({
                properties: { $ai_output: 'The weather is sunny' },
            })
            expect(eventMatchesSearch(event, 'sunny')).toBe(true)
        })

        it('searches in output choices', () => {
            const event = createEvent({
                properties: {
                    $ai_output_choices: [
                        { message: { content: 'First choice' } },
                        { message: { content: 'Second choice' } },
                    ],
                },
            })
            expect(eventMatchesSearch(event, 'first')).toBe(true)
            expect(eventMatchesSearch(event, 'second')).toBe(true)
            expect(eventMatchesSearch(event, 'choice')).toBe(true)
        })

        it('searches in output state', () => {
            const event = createEvent({
                properties: { $ai_output_state: { result: 'completed successfully' } },
            })
            expect(eventMatchesSearch(event, 'completed')).toBe(true)
            expect(eventMatchesSearch(event, 'successfully')).toBe(true)
        })

        it('searches in error messages', () => {
            const event = createEvent({
                properties: { $ai_error: { message: 'API rate limit exceeded', code: 'RATE_LIMIT' } },
            })
            expect(eventMatchesSearch(event, 'rate')).toBe(true)
            expect(eventMatchesSearch(event, 'limit')).toBe(true)
            expect(eventMatchesSearch(event, 'RATE_LIMIT')).toBe(true)
            expect(eventMatchesSearch(event, 'timeout')).toBe(false)
        })

        it('searches across multiple fields', () => {
            const event = createEvent({
                properties: {
                    $ai_span_name: 'Chat Completion',
                    $ai_model: 'gpt-4',
                    $ai_provider: 'OpenAI',
                    $ai_input: 'Tell me about TypeScript',
                    $ai_output: 'TypeScript is a typed superset of JavaScript',
                },
            })
            expect(eventMatchesSearch(event, 'chat')).toBe(true)
            expect(eventMatchesSearch(event, 'gpt')).toBe(true)
            expect(eventMatchesSearch(event, 'openai')).toBe(true)
            expect(eventMatchesSearch(event, 'typescript')).toBe(true)
            expect(eventMatchesSearch(event, 'javascript')).toBe(true)
            expect(eventMatchesSearch(event, 'python')).toBe(false)
        })

        it('searches in deeply nested content', () => {
            const event = createEvent({
                properties: {
                    $ai_input: {
                        conversation: {
                            messages: [
                                {
                                    content: {
                                        parts: [
                                            {
                                                text: {
                                                    data: 'deeply nested search term',
                                                    metadata: {
                                                        source: 'another deep value',
                                                    },
                                                },
                                            },
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                    $ai_output: {
                        response: {
                            data: {
                                nested: {
                                    veryDeep: {
                                        content: 'hidden response text',
                                    },
                                },
                            },
                        },
                    },
                },
            })
            expect(eventMatchesSearch(event, 'deeply nested search term')).toBe(true)
            expect(eventMatchesSearch(event, 'another deep value')).toBe(true)
            expect(eventMatchesSearch(event, 'hidden response text')).toBe(true)
            expect(eventMatchesSearch(event, 'not found anywhere')).toBe(false)
        })
    })

    describe('findSearchOccurrences', () => {
        it('creates occurrences from matches', () => {
            const occurrences = findSearchOccurrences('test test', 'test', 'content', {
                type: 'message',
                eventId: 'event-1',
                messageIndex: 0,
                messageType: 'input',
            })

            expect(occurrences).toEqual([
                {
                    type: 'message',
                    field: 'content',
                    startIndex: 0,
                    eventId: 'event-1',
                    messageIndex: 0,
                    messageType: 'input',
                },
                {
                    type: 'message',
                    field: 'content',
                    startIndex: 5,
                    eventId: 'event-1',
                    messageIndex: 0,
                    messageType: 'input',
                },
            ])
        })

        it('returns empty array for no matches', () => {
            const occurrences = findSearchOccurrences('hello world', 'xyz', 'content', {
                type: 'sidebar',
                eventId: 'event-1',
            })
            expect(occurrences).toEqual([])
        })

        it('uses default type when not specified', () => {
            const occurrences = findSearchOccurrences('test', 'test', 'title', {
                eventId: 'event-1',
            })
            expect(occurrences[0].type).toBe('sidebar')
        })
    })

    describe('findTraceOccurrences', () => {
        it('returns empty array for null trace', () => {
            expect(findTraceOccurrences(null, 'test')).toEqual([])
        })

        it('returns empty array for undefined trace', () => {
            expect(findTraceOccurrences(undefined, 'test')).toEqual([])
        })

        it('returns empty array for empty query', () => {
            const trace = { id: 'trace-1', traceName: 'My Trace' }
            expect(findTraceOccurrences(trace, '')).toEqual([])
            expect(findTraceOccurrences(trace, '  ')).toEqual([])
        })

        it('finds occurrences in trace name', () => {
            const trace = { id: 'trace-1', traceName: 'Test Trace Name' }
            const occurrences = findTraceOccurrences(trace, 'trace')

            expect(occurrences).toEqual([
                {
                    type: 'sidebar',
                    field: 'title',
                    startIndex: 5,
                    eventId: 'trace-1',
                },
            ])
        })

        it('finds multiple occurrences in trace name', () => {
            const trace = { id: 'trace-2', traceName: 'Test test TEST' }
            const occurrences = findTraceOccurrences(trace, 'test')

            expect(occurrences).toHaveLength(3)
            expect(occurrences.map((o) => o.startIndex)).toEqual([0, 5, 10])
        })

        it('handles trace without name', () => {
            const trace = { id: 'trace-3' }
            expect(findTraceOccurrences(trace, 'test')).toEqual([])
        })
    })

    describe('findSidebarOccurrences', () => {
        it('returns empty array for empty query', () => {
            const events = [{ id: 'e1', properties: { $ai_span_name: 'Test' } }]
            expect(findSidebarOccurrences(events, '')).toEqual([])
            expect(findSidebarOccurrences(events, '  ')).toEqual([])
        })

        it('finds occurrences in span name', () => {
            const events = [
                { id: 'e1', properties: { $ai_span_name: 'Chat Completion' } },
                { id: 'e2', properties: { $ai_span_name: 'Text Generation' } },
            ]
            const occurrences = findSidebarOccurrences(events, 'chat')

            expect(occurrences).toEqual([
                {
                    type: 'sidebar',
                    field: 'title',
                    startIndex: 0,
                    eventId: 'e1',
                },
            ])
        })

        it('finds occurrences in model and provider', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Generation',
                        $ai_model: 'gpt-4',
                        $ai_provider: 'OpenAI',
                    },
                },
            ]
            const occurrences = findSidebarOccurrences(events, 'openai')

            expect(occurrences).toEqual([
                {
                    type: 'sidebar',
                    field: 'model',
                    startIndex: 7,
                    eventId: 'e1',
                },
            ])
        })

        it('searches in combined model and provider text', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Gen',
                        $ai_model: 'claude-3',
                        $ai_provider: 'Anthropic',
                    },
                },
            ]
            const occurrences = findSidebarOccurrences(events, 'anthropic')

            expect(occurrences).toEqual([
                {
                    type: 'sidebar',
                    field: 'model',
                    startIndex: 10,
                    eventId: 'e1',
                },
            ])
        })

        it('handles events without model or provider', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: { $ai_span_name: 'Test' },
                },
            ]
            expect(findSidebarOccurrences(events, 'model')).toEqual([])
        })

        it('finds multiple occurrences across events', () => {
            const events = [
                { id: 'e1', properties: { $ai_span_name: 'Test Event' } },
                { id: 'e2', properties: { $ai_span_name: 'Another Test' } },
                {
                    id: 'e3',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Generation Test',
                        $ai_model: 'test-model',
                    },
                },
            ]
            const occurrences = findSidebarOccurrences(events, 'test')

            expect(occurrences).toHaveLength(4)
            expect(occurrences.map((o) => o.eventId)).toEqual(['e1', 'e2', 'e3', 'e3'])
        })
    })

    describe('findMessageOccurrences', () => {
        it('returns empty array for empty query', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: { $ai_input: 'test' },
                },
            ]
            expect(findMessageOccurrences(events, '', normalizeMessages)).toEqual([])
            expect(findMessageOccurrences(events, '  ', normalizeMessages)).toEqual([])
        })

        it('finds occurrences in tools', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_tools: [
                            { name: 'calculator', description: 'math operations' },
                            { name: 'weather', description: 'weather info' },
                        ],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'calculator', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'tools',
                    eventId: 'e1',
                    messageType: 'input',
                })
            )
        })

        it('finds occurrences in input messages', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_input: [
                            { role: 'user', content: 'Hello world' },
                            { role: 'assistant', content: 'Hi there' },
                        ],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'hello', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'content',
                    startIndex: 0,
                    eventId: 'e1',
                    messageIndex: 0,
                    messageType: 'input',
                })
            )
        })

        it('finds occurrences in output messages', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_output_choices: [{ role: 'assistant', content: 'The answer is 42' }],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'answer', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'content',
                    startIndex: 4,
                    eventId: 'e1',
                    messageIndex: 0,
                    messageType: 'output',
                })
            )
        })

        it('finds occurrences in additional kwargs', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_input: [
                            {
                                role: 'user',
                                content: 'test',
                                customField: 'special value',
                                metadata: { key: 'value' },
                            },
                        ],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'special', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'additionalKwargs',
                    eventId: 'e1',
                    messageIndex: 0,
                    messageType: 'input',
                })
            )
        })

        it('finds occurrences in error messages', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_error: { message: 'Rate limit exceeded', code: 'RATE_LIMIT' },
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'limit', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'error',
                    eventId: 'e1',
                })
            )
        })

        it('handles non-generation events', () => {
            const events = [
                {
                    id: 'e1',
                    properties: {
                        $ai_input: [{ role: 'user', content: 'Non-gen input' }],
                        $ai_output: [{ role: 'assistant', content: 'Non-gen output' }],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'non-gen', normalizeMessages)

            expect(occurrences).toHaveLength(2)
            expect(occurrences.map((o) => o.field)).toContain('content')
        })

        it('handles complex nested content', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_input: [
                            {
                                role: 'user',
                                content: {
                                    type: 'image',
                                    url: 'https://example.com/image.jpg',
                                    description: 'A beautiful landscape',
                                },
                            },
                        ],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'landscape', normalizeMessages)

            expect(occurrences).toContainEqual(
                expect.objectContaining({
                    type: 'message',
                    field: 'content',
                    eventId: 'e1',
                })
            )
        })

        it('assigns correct message indices', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_input: [
                            { role: 'user', content: 'First message with TEST' },
                            { role: 'user', content: 'Second message with TEST' },
                            { role: 'user', content: 'Third message with TEST' },
                        ],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'TEST', normalizeMessages)

            const indices = occurrences.filter((o) => o.field === 'content').map((o) => o.messageIndex)
            expect(indices).toEqual([0, 1, 2])
        })

        it('differentiates input and output message types', () => {
            const events = [
                {
                    id: 'e1',
                    event: '$ai_generation',
                    properties: {
                        $ai_input: [{ role: 'user', content: 'Input TEST' }],
                        $ai_output: [{ role: 'assistant', content: 'Output TEST' }],
                    },
                },
            ]
            const occurrences = findMessageOccurrences(events, 'TEST', normalizeMessages)

            const inputOccurrences = occurrences.filter((o) => o.messageType === 'input')
            const outputOccurrences = occurrences.filter((o) => o.messageType === 'output')

            expect(inputOccurrences).toHaveLength(1)
            expect(outputOccurrences).toHaveLength(1)
        })
    })

    describe('findEventWithParents', () => {
        it('finds parent chain for deeply nested events', () => {
            const traceId = 'trace-123'

            // Create a chain: trace -> span1 -> span2 -> generation
            const events: LLMTraceEvent[] = [
                {
                    id: 'span1',
                    event: '$ai_span',
                    properties: {
                        $ai_span_id: 'span1',
                        $ai_trace_id: traceId,
                        $ai_span_name: 'Parent Span 1',
                    },
                    createdAt: '2023-01-01T00:00:00Z',
                },
                {
                    id: 'span2',
                    event: '$ai_span',
                    properties: {
                        $ai_span_id: 'span2',
                        $ai_parent_id: 'span1',
                        $ai_span_name: 'Parent Span 2',
                    },
                    createdAt: '2023-01-01T00:01:00Z',
                },
                {
                    id: 'gen1',
                    event: '$ai_generation',
                    properties: {
                        $ai_generation_id: 'gen1',
                        $ai_parent_id: 'span2',
                        $ai_span_name: 'Deep Generation',
                        $ai_input: 'deeply nested search query',
                        $ai_output: 'response from deep generation',
                    },
                    createdAt: '2023-01-01T00:02:00Z',
                },
            ]

            // Test that searching for text in the deep generation includes parent chain
            const deepEvent = events[2] // gen1
            const parentChain = findEventWithParents(deepEvent, events, traceId)

            expect(parentChain).toHaveLength(3)
            expect(parentChain.map((e) => e.id)).toEqual(['gen1', 'span2', 'span1'])
            expect(parentChain[0].properties.$ai_span_name).toBe('Deep Generation')
            expect(parentChain[1].properties.$ai_span_name).toBe('Parent Span 2')
            expect(parentChain[2].properties.$ai_span_name).toBe('Parent Span 1')
        })

        it('handles events with no parents', () => {
            const traceId = 'trace-123'
            const events: LLMTraceEvent[] = [
                {
                    id: 'span1',
                    event: '$ai_span',
                    properties: {
                        $ai_span_id: 'span1',
                        $ai_trace_id: traceId,
                        $ai_span_name: 'Root Span',
                    },
                    createdAt: '2023-01-01T00:00:00Z',
                },
            ]

            const parentChain = findEventWithParents(events[0], events, traceId)
            expect(parentChain).toHaveLength(1)
            expect(parentChain[0].id).toBe('span1')
        })
    })
})
