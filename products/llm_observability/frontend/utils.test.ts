import { AnthropicInputMessage, OpenAICompletionMessage } from './types'
import { normalizeMessage, looksLikeXml, formatLLMEventTitle } from './utils'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

describe('LLM Observability utils', () => {
    it('normalizeOutputMessage: parses OpenAI message', () => {
        const message: OpenAICompletionMessage = {
            role: 'assistant',
            content: 'Hello, world!',
        }
        expect(normalizeMessage(message)).toEqual([
            {
                role: 'assistant',
                content: 'Hello, world!',
            },
        ])
    })

    it('normalizeOutputMessage: stringifies incomplete OpenAI message', () => {
        const message = {
            role: 'assistant',
        }
        // When no defaultRole is provided, it defaults to 'user'
        expect(normalizeMessage(message)).toEqual([
            {
                role: 'user',
                content: JSON.stringify(message),
            },
        ])

        // When 'assistant' is provided as defaultRole, it uses that
        expect(normalizeMessage(message, 'assistant')).toEqual([
            {
                role: 'assistant',
                content: JSON.stringify(message),
            },
        ])
    })

    it('normalizeOutputMessage: parses OpenAI tool calls', () => {
        const message = {
            role: 'assistant',
            content: '',
            tool_calls: [
                {
                    type: 'function',
                    id: '123',
                    function: {
                        name: 'test',
                        arguments: '{"foo": "bar"}',
                    },
                },
                {
                    type: 'function',
                    id: '456',
                    function: {
                        name: 'test2',
                        arguments: '{"bar": "baz"}',
                    },
                },
            ],
        }
        expect(normalizeMessage(message)).toEqual([
            {
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: '123',
                        function: {
                            name: 'test',
                            arguments: { foo: 'bar' },
                        },
                    },
                    {
                        type: 'function',
                        id: '456',
                        function: {
                            name: 'test2',
                            arguments: { bar: 'baz' },
                        },
                    },
                ],
            },
        ])
    })

    it('normalizeOutputMessage: parses OpenAI tool use', () => {
        const message = {
            role: 'tool',
            content: 'response',
            tool_call_id: '456',
        }

        expect(normalizeMessage(message)).toEqual([
            {
                role: 'tool',
                content: 'response',
                tool_call_id: '456',
            },
        ])
    })

    it('normalizeOutputMessage: parses a string message', () => {
        // When no defaultRole is provided, it defaults to 'user'
        expect(normalizeMessage('foo')).toEqual([
            {
                role: 'user',
                content: 'foo',
            },
        ])

        // When 'assistant' is provided as defaultRole, it uses that
        expect(normalizeMessage('foo', 'assistant')).toEqual([
            {
                role: 'assistant',
                content: 'foo',
            },
        ])
    })

    it('normalizeOutputMessage: parses an Anthropic tool call message', () => {
        let message: any = {
            type: 'tool_use',
            id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
            name: 'get_stock_price',
            input: { ticker: '^GSPC' },
        }

        expect(normalizeMessage(message, 'assistant')).toEqual([
            {
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                        function: {
                            name: 'get_stock_price',
                            arguments: { ticker: '^GSPC' },
                        },
                    },
                ],
            },
        ])

        message = {
            role: 'assistant',
            content: [
                {
                    type: 'tool_use',
                    id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                    name: 'get_stock_price',
                    input: { ticker: '^GSPC' },
                },
                {
                    type: 'tool_use',
                    id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV2',
                    name: 'get_stock_price',
                    input: { ticker: '^GSPC' },
                },
            ],
        }

        expect(normalizeMessage(message, 'assistant')).toEqual([
            {
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                        function: {
                            name: 'get_stock_price',
                            arguments: { ticker: '^GSPC' },
                        },
                    },
                ],
            },
            {
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV2',
                        function: {
                            name: 'get_stock_price',
                            arguments: { ticker: '^GSPC' },
                        },
                    },
                ],
            },
        ])
    })

    it('normalizeOutputMessage: parses an Anthropic tool result message', () => {
        let message: AnthropicInputMessage = {
            role: 'user',
            content: [
                {
                    type: 'tool_result',
                    tool_use_id: '1',
                    content: 'foo',
                },
            ],
        }

        expect(normalizeMessage(message)).toEqual([
            {
                role: 'user',
                content: 'foo',
                tool_call_id: '1',
            },
        ])

        message = {
            role: 'user',
            content: [
                {
                    type: 'tool_result',
                    tool_use_id: '1',
                    content: [
                        {
                            type: 'text',
                            text: 'foo',
                        },
                    ],
                },
            ],
        }
        expect(normalizeMessage(message)).toEqual([
            {
                role: 'user',
                content: 'foo',
                tool_call_id: '1',
            },
        ])
    })

    it('normalizeMessage: handles new array-based content format', () => {
        const message = {
            role: 'assistant',
            content: [
                {
                    type: 'text',
                    text: "I'll check the weather for you.",
                },
                {
                    type: 'function',
                    id: 'call_123',
                    function: {
                        name: 'get_weather',
                        arguments: { location: 'New York City' },
                    },
                },
            ],
        }

        expect(normalizeMessage(message)).toEqual([
            {
                role: 'assistant',
                content: [
                    {
                        type: 'text',
                        text: "I'll check the weather for you.",
                    },
                    {
                        type: 'function',
                        id: 'call_123',
                        function: {
                            name: 'get_weather',
                            arguments: { location: 'New York City' },
                        },
                    },
                ],
            },
        ])
    })

    describe('looksLikeXml', () => {
        it('detects basic XML structures', () => {
            expect(looksLikeXml('<root><child/></root>')).toBe(true)
            expect(looksLikeXml('<?xml version="1.0"?><root></root>')).toBe(true)
            expect(looksLikeXml('<root attr="1">text</root>')).toBe(true)
            expect(looksLikeXml('<self-closing/>')).toBe(true)
        })

        it('returns true for typical HTML snippets (by design)', () => {
            expect(looksLikeXml('<!DOCTYPE html><html><body></body></html>')).toBe(true)
            expect(looksLikeXml('<div class="x">hi</div>')).toBe(true)
        })

        it('returns false for non-XML-like strings', () => {
            expect(looksLikeXml('a < b and c > d')).toBe(false)
            expect(looksLikeXml('plain text')).toBe(false)
            expect(looksLikeXml('{"foo":"bar"}')).toBe(false)
        })
    })

    describe('formatLLMEventTitle', () => {
        it('formats LLMTrace with traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                traceName: 'My Custom Trace',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('My Custom Trace')
        })

        it('formats LLMTrace without traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('Trace')
        })

        describe('$ai_generation events', () => {
            it('formats generation event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Chat Completion',
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Chat Completion')
            })

            it('formats generation event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4 (openai)')
            })

            it('formats generation event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4')
            })

            it('formats generation event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Generation')
            })
        })

        describe('$ai_embedding events', () => {
            it('formats embedding event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_span_name: 'Document Embedding',
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Document Embedding')
            })

            it('formats embedding event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small (openai)')
            })

            it('formats embedding event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small')
            })

            it('formats embedding event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Embedding')
            })
        })

        describe('$ai_span and other events', () => {
            it('formats span event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {
                        $ai_span_name: 'Database Query',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Database Query')
            })

            it('formats span event without span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Span')
            })

            it('formats metric event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_metric',
                    properties: {
                        $ai_span_name: 'Performance Metric',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Performance Metric')
            })

            it('formats feedback event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_feedback',
                    properties: {
                        $ai_span_name: 'User Feedback',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('User Feedback')
            })

            it('formats unknown event type', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: 'custom_event',
                    properties: {
                        $ai_span_name: 'Custom Action',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Custom Action')
            })
        })
    })
})
