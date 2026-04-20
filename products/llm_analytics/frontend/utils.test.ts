import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { AnthropicInputMessage, OpenAICompletionMessage } from './types'
import {
    costContextFromProperties,
    costContextFromTrace,
    formatLLMEventTitle,
    getSessionID,
    getSessionStartTimestamp,
    hasCostBreakdown,
    isLangChainMessage,
    looksLikeXml,
    normalizeMessage,
    normalizeMessages,
    parseOpenAIToolCalls,
    parsePartialJSON,
    sanitizeTraceUrlSearchParams,
} from './utils'

describe('LLM Analytics utils', () => {
    beforeEach(() => {
        console.warn = jest.fn()
    })

    describe('getSessionStartTimestamp', () => {
        it.each([
            ['2024-01-15T12:00:00Z', '2024-01-14T12:00:00Z'],
            ['2024-01-01T00:00:00Z', '2023-12-31T00:00:00Z'],
            ['2024-03-01T06:30:00Z', '2024-02-29T06:30:00Z'],
        ])('subtracts 24 hours from %s to get %s', (input, expected) => {
            expect(getSessionStartTimestamp(input)).toBe(expected)
        })
    })

    describe('sanitizeTraceUrlSearchParams', () => {
        it.each([
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    timestamp: '2026-01-29T22:07:59Z',
                    exception_ts: '2026-01-29T22:07:59Z',
                    line: '5',
                    tab: 'conversation',
                    back_to: 'traces',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
                {},
                {
                    date_from: '-30d',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
            ],
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    search: 'foo',
                    back_to: 'generations',
                },
                { removeSearch: true },
                { date_from: '-30d' },
            ],
        ])('removes trace-scoped URL params', (searchParams, options, expected) => {
            expect(sanitizeTraceUrlSearchParams(searchParams, options)).toEqual(expected)
        })
    })

    describe('normalizeOutputMessage', () => {
        it('parses OpenAI message', () => {
            const message: OpenAICompletionMessage = {
                role: 'assistant',
                content: 'Hello, world!',
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: 'Hello, world!',
                },
            ])
        })

        it('stringifies incomplete OpenAI message', () => {
            const message = {
                role: 'assistant',
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: JSON.stringify(message),
                },
            ])

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: JSON.stringify(message),
                },
            ])
        })

        it('parses OpenAI tool calls', () => {
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
            expect(normalizeMessage(message, 'user')).toEqual([
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

        it('parses OpenAI tool use', () => {
            const message = {
                role: 'tool',
                content: 'response',
                tool_call_id: '456',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'tool',
                    content: 'response',
                    tool_call_id: '456',
                },
            ])
        })

        it('parses a string message', () => {
            expect(normalizeMessage('foo', 'user')).toEqual([
                {
                    role: 'user',
                    content: 'foo',
                },
            ])

            expect(normalizeMessage('foo', 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: 'foo',
                },
            ])
        })

        it('parses an Anthropic tool call message', () => {
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

        it('prefers top-level tool_calls over content tool_use blocks', () => {
            // This is the format produced by LangChain's Anthropic callback
            // content has raw Anthropic format with empty input (streaming artifact)
            // tool_calls has the normalized OpenAI format with correct arguments
            const message = {
                role: 'assistant',
                content: [
                    { type: 'text', text: 'Let me check that.' },
                    {
                        type: 'tool_use',
                        id: 'toolu_123',
                        name: 'get_weather',
                        input: {}, // Empty - streaming artifact
                    },
                ],
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_123',
                        function: {
                            name: 'get_weather',
                            arguments: '{"location": "San Francisco"}', // Correct arguments
                        },
                    },
                ],
            }

            const result = normalizeMessage(message, 'assistant')

            // Should use the tool_calls array, not extract from content
            expect(result).toHaveLength(2)
            expect(result[0]).toEqual({
                role: 'assistant',
                content: 'Let me check that.',
            })
            expect(result[1]).toEqual({
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_123',
                        function: {
                            name: 'get_weather',
                            arguments: { location: 'San Francisco' },
                        },
                    },
                ],
            })
        })

        it('parses an Anthropic tool result message', () => {
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

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
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
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: 'foo',
                    tool_call_id: '1',
                },
            ])
        })
    })

    describe('OpenAI Responses API', () => {
        it('parses a function_call item as an assistant tool call', () => {
            const message = {
                type: 'function_call',
                call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                name: 'search_category',
                arguments: '{"dimensions":[],"list_all":true}',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                            function: {
                                name: 'search_category',
                                arguments: { dimensions: [], list_all: true },
                            },
                        },
                    ],
                },
            ])
        })

        it('parses a function_call_output item as a tool result', () => {
            const message = {
                type: 'function_call_output',
                call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                output: '{"categories":[{"id":"149288","name":"Asheville Cloud Shaker"}]}',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '{"categories":[{"id":"149288","name":"Asheville Cloud Shaker"}]}',
                    tool_call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                },
            ])
        })

        it('parses a reasoning item as assistant thinking', () => {
            const message = {
                type: 'reasoning',
                id: 'rs_123',
                summary: [
                    { type: 'summary_text', text: 'Thinking about the query...' },
                    { type: 'summary_text', text: 'Deciding on a response.' },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'Thinking about the query...\nDeciding on a response.',
                },
            ])
        })

        it('handles reasoning with no summary', () => {
            const message = {
                type: 'reasoning',
                id: 'rs_456',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: '',
                },
            ])
        })

        it('handles Vercel AI SDK reasoning with text field', () => {
            const message = {
                type: 'reasoning',
                text: 'Let me think about this step by step.',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'Let me think about this step by step.',
                },
            ])
        })

        it.each([
            [
                'string arguments (posthog-node format)',
                {
                    type: 'tool-call',
                    id: 'toolu_vrtx_01CTHfH7tfd2vNWSWJhKzfov',
                    function: { name: 'queryModel', arguments: '{"query": "relevant data"}' },
                },
                'toolu_vrtx_01CTHfH7tfd2vNWSWJhKzfov',
                'queryModel',
                { query: 'relevant data' },
            ],
            [
                'object arguments (posthog-node format)',
                {
                    type: 'tool-call',
                    id: 'call_123',
                    function: { name: 'get_weather', arguments: { location: 'NYC' } },
                },
                'call_123',
                'get_weather',
                { location: 'NYC' },
            ],
            [
                'native Vercel SDK format (toolName/input/toolCallId)',
                { type: 'tool-call', toolCallId: 'tc_native_123', toolName: 'get_weather', input: { location: 'NYC' } },
                'tc_native_123',
                'get_weather',
                { location: 'NYC' },
            ],
        ])('handles Vercel AI SDK tool-call with %s', (_label, message, expectedId, expectedName, expectedArgs) => {
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: expectedId,
                            function: { name: expectedName, arguments: expectedArgs },
                        },
                    ],
                },
            ])
        })

        it.each([
            [
                'object output',
                {
                    type: 'tool-result',
                    toolCallId: 'tc_123',
                    toolName: 'get_weather',
                    output: { temperature: 72, unit: 'F' },
                },
                '{"temperature":72,"unit":"F"}',
                'tc_123',
            ],
            [
                'string output',
                { type: 'tool-result', toolCallId: 'tc_456', toolName: 'search', output: 'Found 3 results' },
                'Found 3 results',
                'tc_456',
            ],
        ])('handles Vercel AI SDK tool-result with %s', (_label, message, expectedContent, expectedToolCallId) => {
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: expectedContent,
                    tool_call_id: expectedToolCallId,
                },
            ])
        })

        it('handles Vercel AI SDK toolName variant with string input', () => {
            const message = { type: 'tool-call', toolCallId: 'tc_1', toolName: 'run_code', input: 'print("hi")' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'tc_1',
                            function: { name: 'run_code', arguments: 'print("hi")' },
                        },
                    ],
                },
            ])
        })

        it('handles Vercel AI SDK toolName variant with missing input', () => {
            const message = { type: 'tool-call', toolCallId: 'tc_2', toolName: 'no_args_tool' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'tc_2',
                            function: { name: 'no_args_tool', arguments: {} },
                        },
                    ],
                },
            ])
        })

        it('prefers function variant when both function and toolName are present', () => {
            const message = {
                type: 'tool-call',
                id: 'func_id',
                function: { name: 'from_function', arguments: '{"a":1}' },
                toolCallId: 'tool_id',
                toolName: 'from_toolName',
                input: { b: 2 },
            }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'func_id',
                            function: { name: 'from_function', arguments: { a: 1 } },
                        },
                    ],
                },
            ])
        })

        it('handles Vercel AI SDK tool-result with undefined output', () => {
            const message = { type: 'tool-result', toolCallId: 'tc_empty', toolName: 'void_tool' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '',
                    tool_call_id: 'tc_empty',
                },
            ])
        })

        it('handles Vercel AI SDK tool-result with non-serializable output', () => {
            const circular: Record<string, unknown> = { key: 'value' }
            circular.self = circular
            const message = { type: 'tool-result', toolCallId: 'tc_circ', toolName: 'bad_tool', output: circular }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '[object Object]',
                    tool_call_id: 'tc_circ',
                },
            ])
        })

        it('handles Vercel AI SDK mixed content array with reasoning + text + tool-call', () => {
            const message = {
                role: 'assistant',
                content: [
                    { type: 'reasoning', text: 'I should use a tool to look up the data.' },
                    { type: 'text', text: 'Let me check that for you.' },
                    {
                        type: 'tool-call',
                        id: 'toolu_vrtx_abc',
                        function: { name: 'queryModel', arguments: '{"query":"data"}' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'I should use a tool to look up the data.',
                },
                {
                    role: 'assistant',
                    content: 'Let me check that for you.',
                },
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'toolu_vrtx_abc',
                            function: { name: 'queryModel', arguments: { query: 'data' } },
                        },
                    ],
                },
            ])
        })

        it.each([
            ['web_search_call', 'ws_123', { type: 'web_search_call', id: 'ws_123', status: 'completed' }],
            [
                'code_interpreter_call',
                'ci_123',
                { type: 'code_interpreter_call', id: 'ci_123', status: 'completed', code: 'print("hello")' },
            ],
            ['image_generation_call', 'ig_123', { type: 'image_generation_call', id: 'ig_123', status: 'completed' }],
            ['mcp_call', 'mcp_123', { type: 'mcp_call', id: 'mcp_123', status: 'completed' }],
            ['file_search_call', 'fs_123', { type: 'file_search_call', id: 'fs_123', status: 'completed' }],
            ['computer_call', 'cc_123', { type: 'computer_call', id: 'cc_123', status: 'completed' }],
        ])('parses %s as an assistant tool call', (toolType, toolId, message) => {
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: JSON.stringify(message),
                    tool_calls: [{ type: 'function', id: toolId, function: { name: toolType, arguments: {} } }],
                },
            ])
        })

        it('handles function_call with unparseable arguments', () => {
            const message = {
                type: 'function_call',
                call_id: 'call_abc',
                name: 'my_func',
                arguments: '{invalid json',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_abc',
                            function: {
                                name: 'my_func',
                                arguments: '{invalid json',
                            },
                        },
                    ],
                },
            ])
        })
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

        expect(normalizeMessage(message, 'assistant')).toEqual([
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

    describe('role preservation in nested content', () => {
        it('preserves assistant role when recursing into nested array content with output_text', () => {
            // This is the bug we fixed - messages with role + array content should preserve the role
            // Now output_text is properly recognized and content is preserved as array
            const message = {
                role: 'assistant',
                content: [
                    {
                        type: 'output_text',
                        text: 'Hello! How can I help you?',
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant') // Role is preserved!
            expect(result[0].content).toEqual([
                {
                    type: 'output_text',
                    text: 'Hello! How can I help you?',
                },
            ])
        })

        it('preserves system role when recursing into nested array content with output_text', () => {
            const message = {
                role: 'system',
                content: [
                    {
                        type: 'output_text',
                        text: 'You are a helpful assistant.',
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('system') // Role is preserved!
            expect(result[0].content).toEqual([
                {
                    type: 'output_text',
                    text: 'You are a helpful assistant.',
                },
            ])
        })

        it('preserves role even when defaultRole is different', () => {
            const assistantMessage = {
                role: 'assistant',
                content: [{ type: 'output_text', text: 'Response' }],
            }

            // Even though defaultRole is 'user', the actual role 'assistant' should be preserved
            const result = normalizeMessage(assistantMessage, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant') // Key test: role is preserved despite different defaultRole
            expect(result[0].content).toEqual([{ type: 'output_text', text: 'Response' }])
        })

        it('preserves input_text content type', () => {
            const message = {
                role: 'user',
                content: [{ type: 'input_text', text: 'What is the weather?' }],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('user')
            expect(result[0].content).toEqual([{ type: 'input_text', text: 'What is the weather?' }])
        })

        it('uses defaultRole when message has no role property', () => {
            const messageWithoutRole = {
                type: 'output_text',
                text: 'Some text',
            }

            const result = normalizeMessage(messageWithoutRole, 'assistant')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            // Without a role wrapper, output_text falls through to unsupported and gets stringified
            expect(result[0].content).toBe('{"type":"output_text","text":"Some text"}')
        })

        it('handles Anthropic tool result with nested content and overrides role to assistant (tool result)', () => {
            const toolResultMessage = {
                type: 'tool_result',
                tool_use_id: 'tool_123',
                content: [
                    {
                        type: 'text',
                        text: 'Weather is sunny',
                    },
                ],
            }

            const result = normalizeMessage(toolResultMessage, 'tool')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant (tool result)')
            expect(result[0].content).toBe('Weather is sunny')
            expect(result[0].tool_call_id).toBe('tool_123')
        })

        it('preserves custom/unknown roles', () => {
            const customRoleMessage = {
                role: 'custom_agent',
                content: [{ type: 'text', text: 'Custom response' }],
            }

            const result = normalizeMessage(customRoleMessage, 'user')

            // Unknown roles should be preserved as-is (lowercased)
            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('custom_agent')
            expect(result[0].content).toEqual([{ type: 'text', text: 'Custom response' }])
        })

        it.each([
            [
                'single text block',
                {
                    role: 'user',
                    content: JSON.stringify([
                        { type: 'text', text: 'lets respond inline to each bot to explain that its fine' },
                    ]),
                },
                [{ type: 'text', text: 'lets respond inline to each bot to explain that its fine' }],
            ],
            ['plain string stays plain', { role: 'user', content: 'plain text' }, 'plain text'],
            ['invalid JSON falls back to raw string', { role: 'user', content: '[not json' }, '[not json'],
            [
                'unknown block types stay as raw string',
                { role: 'user', content: JSON.stringify([{ type: 'schema', definition: { foo: 'bar' } }]) },
                '[{"type":"schema","definition":{"foo":"bar"}}]',
            ],
            ['empty structured array parses as empty array', { role: 'user', content: '[]' }, []],
        ])(
            'handles stringified structured content in OpenAI-compatible messages: %s',
            (_label, message, expectedContent) => {
                const result = normalizeMessage(message, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('user')
                expect(result[0].content).toEqual(expectedContent)
            }
        )

        it('handles LiteLLM choice wrapper and preserves nested role', () => {
            const liteLLMChoice = {
                finish_reason: 'stop',
                index: 0,
                message: {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'Response from LiteLLM' }],
                },
            }

            const result = normalizeMessage(liteLLMChoice, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            expect(result[0].content).toEqual([{ type: 'text', text: 'Response from LiteLLM' }])
        })
    })

    describe('parsePartialJSON', () => {
        it.each([
            ['full object', '{"key": "value", "n": 42}', { key: 'value', n: 42 }],
            ['full array', '[1, 2, 3]', [1, 2, 3]],
            ['truncated object', '{"key": "value", "long_field": "some te', { key: 'value', long_field: 'some te' }],
            ['truncated nested object', '{"a": {"b": "c", "d": "efg', { a: { b: 'c', d: 'efg' } }],
            ['truncated array', '[1, 2, "hel', [1, 2, 'hel']],
            ['truncated string value', '"hello wor', 'hello wor'],
        ])('%s', (_label, input, expected) => {
            expect(parsePartialJSON(input)).toEqual(expected)
        })

        it('throws on completely invalid input', () => {
            expect(() => parsePartialJSON('not json at all')).toThrow()
        })

        it.each([
            ['bracket-prefixed text', '[Thinking: The user wants to build a todo app.]I will build it'],
            ['bracket-prefixed with tool call', '[Tool Call: lov-write, Input: {"file_path":"src/index.tsx"}]'],
        ])('returns empty array for %s (not actual JSON)', (_label, input) => {
            // These strings start with "[" so they look like JSON arrays,
            // but the partial parser can't extract any valid elements
            const result = parsePartialJSON(input)
            expect(result).toEqual([])
        })
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
                distinctId: 'user-1',
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
                distinctId: 'user-1',
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

    describe('LiteLLM support', () => {
        const litellmChoice = {
            finish_reason: 'stop',
            index: 0,
            message: {
                annotations: [],
                content:
                    "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                function_call: null,
                role: 'assistant',
                tool_calls: null,
            },
            provider_specific_fields: {},
        }

        const litellmResponse = {
            choices: [litellmChoice],
            model: 'gpt-3.5-turbo',
            usage: { prompt_tokens: 10, completion_tokens: 25, total_tokens: 35 },
        }

        describe('normalizeMessage', () => {
            it('should handle LiteLLM choice format', () => {
                const result = normalizeMessage(litellmChoice, 'user')

                expect(result).toHaveLength(1)
                expect(result[0]).toMatchObject({
                    role: 'assistant',
                    content:
                        "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                    function_call: null,
                })
                expect(result[0].tool_calls).toBeUndefined()
            })

            it('should handle LiteLLM choice with tool calls', () => {
                const choiceWithTools = {
                    ...litellmChoice,
                    message: {
                        ...litellmChoice.message,
                        content: null,
                        tool_calls: [
                            {
                                type: 'function',
                                id: 'call_123',
                                function: {
                                    name: 'get_weather',
                                    arguments: '{"location": "San Francisco"}',
                                },
                            },
                        ],
                    },
                }

                const result = normalizeMessage(choiceWithTools, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('assistant')
                expect(result[0].tool_calls).toHaveLength(1)
                expect(result[0].tool_calls![0].function.name).toBe('get_weather')
            })
        })

        describe('normalizeMessages', () => {
            it('should handle LiteLLM response format', () => {
                const result = normalizeMessages(litellmResponse, 'assistant')

                expect(result).toHaveLength(1)
                expect(result[0]).toMatchObject({
                    role: 'assistant',
                    content:
                        "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                    function_call: null,
                })
                expect(result[0].tool_calls).toBeUndefined()
            })

            it('should handle LiteLLM response with multiple choices', () => {
                const multiChoiceResponse = {
                    choices: [
                        litellmChoice,
                        {
                            ...litellmChoice,
                            index: 1,
                            message: {
                                ...litellmChoice.message,
                                content: 'Alternative response',
                            },
                        },
                    ],
                }

                const result = normalizeMessages(multiChoiceResponse, 'assistant')

                expect(result).toHaveLength(2)
                expect(result[0].content).toBe(
                    "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!"
                )
                expect(result[1].content).toBe('Alternative response')
            })

            it('should handle empty LiteLLM response gracefully', () => {
                const emptyResponse = { choices: [] }
                const result = normalizeMessages(emptyResponse, 'assistant')

                expect(result).toHaveLength(0)
            })
        })

        describe('Role normalization', () => {
            it('should preserve system role in array-based content', () => {
                const systemMessage = {
                    role: 'system',
                    content: [{ type: 'text', text: 'You are a helpful assistant.' }],
                }

                const result = normalizeMessage(systemMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('system')
                expect(result[0].content).toEqual([{ type: 'text', text: 'You are a helpful assistant.' }])
            })

            it('should preserve system role in string content', () => {
                const systemMessage = {
                    role: 'system',
                    content: 'You are a helpful assistant.',
                }

                const result = normalizeMessage(systemMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('system')
                expect(result[0].content).toBe('You are a helpful assistant.')
            })

            it('should map known provider roles', () => {
                const humanMessage = {
                    role: 'human',
                    content: 'Hello',
                }

                const result = normalizeMessage(humanMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('user')
                expect(result[0].content).toBe('Hello')
            })
        })
    })

    describe('LangChain/LangGraph format', () => {
        it.each([
            ['human type', { type: 'human', content: 'Hello' }, true],
            ['ai type', { type: 'ai', content: 'Hi there', tool_calls: [] }, true],
            ['tool type', { type: 'tool', content: 'result', tool_call_id: 'toolu_123' }, true],
            ['context type', { type: 'context', content: '<system_reminder>...' }, true],
            ['rejects messages with role field', { role: 'user', type: 'human', content: 'Hello' }, false],
            ['rejects unknown types', { type: 'text', content: 'Hello' }, false],
        ])('isLangChainMessage: %s', (_, input, expected) => {
            expect(isLangChainMessage(input)).toBe(expected)
        })

        it('normalizeMessage maps human type to user role', () => {
            const message = { type: 'human', content: 'Hello', id: 'msg-1' }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([{ role: 'user', content: 'Hello' }])
        })

        it('normalizeMessage maps ai type to assistant role', () => {
            const message = { type: 'ai', content: 'Hi there', id: 'msg-2', meta: {} }
            const result = normalizeMessage(message, 'user')
            expect(result).toEqual([{ role: 'assistant', content: 'Hi there' }])
        })

        it('normalizeMessage handles ai type with tool_calls', () => {
            const message = {
                type: 'ai',
                content: '',
                tool_calls: [
                    {
                        type: 'function' as const,
                        id: 'toolu_123',
                        function: { name: 'search', arguments: '{"q":"test"}' },
                    },
                ],
            }
            const result = normalizeMessage(message, 'user')
            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            expect(result[0].tool_calls).toHaveLength(1)
            expect(result[0].tool_calls![0].function.name).toBe('search')
        })

        it('normalizeMessage handles tool type with tool_call_id', () => {
            const message = {
                type: 'tool',
                content: 'Search results: ...',
                tool_call_id: 'toolu_123',
            }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([{ role: 'assistant', content: 'Search results: ...', tool_call_id: 'toolu_123' }])
        })

        it('normalizeMessage maps context type to system role', () => {
            const message = { type: 'context', content: '<system_reminder>Your initial mode is sql.</system_reminder>' }
            const result = normalizeMessage(message, 'user')
            expect(result).toEqual([
                { role: 'system', content: '<system_reminder>Your initial mode is sql.</system_reminder>' },
            ])
        })
    })

    describe('parseOpenAIToolCalls', () => {
        it('should parse valid JSON arguments in tool calls', () => {
            const toolCalls = [
                {
                    type: 'function' as const,
                    id: 'call-123',
                    function: {
                        name: 'test_function',
                        arguments: '{"key": "value", "number": 42}',
                    },
                },
            ]

            const result = parseOpenAIToolCalls(toolCalls)

            expect(result).toEqual([
                {
                    type: 'function',
                    id: 'call-123',
                    function: {
                        name: 'test_function',
                        arguments: { key: 'value', number: 42 },
                    },
                },
            ])
        })

        it('should handle malformed JSON arguments gracefully', () => {
            const toolCalls = [
                {
                    type: 'function' as const,
                    id: 'call-456',
                    function: {
                        name: 'test_function',
                        arguments: 'invalid json {not valid}',
                    },
                },
            ]

            const result = parseOpenAIToolCalls(toolCalls)

            // Should keep the original string if parsing fails
            expect(result).toEqual([
                {
                    type: 'function',
                    id: 'call-456',
                    function: {
                        name: 'test_function',
                        arguments: 'invalid json {not valid}',
                    },
                },
            ])
        })

        it('should handle mixed valid and invalid JSON in multiple tool calls', () => {
            const toolCalls = [
                {
                    type: 'function' as const,
                    id: 'call-1',
                    function: {
                        name: 'func1',
                        arguments: '{"valid": "json"}',
                    },
                },
                {
                    type: 'function' as const,
                    id: 'call-2',
                    function: {
                        name: 'func2',
                        arguments: 'not valid json',
                    },
                },
            ]

            const result = parseOpenAIToolCalls(toolCalls)

            expect(result).toEqual([
                {
                    type: 'function',
                    id: 'call-1',
                    function: {
                        name: 'func1',
                        arguments: { valid: 'json' },
                    },
                },
                {
                    type: 'function',
                    id: 'call-2',
                    function: {
                        name: 'func2',
                        arguments: 'not valid json',
                    },
                },
            ])
        })
    })

    describe('OTel parts format', () => {
        it('normalizes a single text part into a string content', () => {
            const message = {
                role: 'assistant',
                parts: [{ type: 'text', content: 'Hello from OTel!' }],
            }

            expect(normalizeMessage(message, 'user')).toEqual([{ role: 'assistant', content: 'Hello from OTel!' }])
        })

        it('normalizes multiple text parts into an array content', () => {
            const message = {
                role: 'assistant',
                parts: [
                    { type: 'text', content: 'First part.' },
                    { type: 'text', content: 'Second part.' },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: [
                        { type: 'text', text: 'First part.' },
                        { type: 'text', text: 'Second part.' },
                    ],
                },
            ])
        })

        it('normalizes tool_call parts into CompatToolCall format', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: { location: 'London' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { location: 'London' },
                            },
                        },
                    ],
                },
            ])
        })

        it('handles mixed text and tool_call parts', () => {
            const message = {
                role: 'assistant',
                parts: [
                    { type: 'text', content: 'Let me check that.' },
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: { location: 'London' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: 'Let me check that.',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { location: 'London' },
                            },
                        },
                    ],
                },
            ])
        })

        it('preserves top-level fields via spread', () => {
            const message = {
                role: 'assistant',
                finish_reason: 'stop',
                parts: [{ type: 'text', content: 'Done.' }],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                { role: 'assistant', finish_reason: 'stop', content: 'Done.' },
            ])
        })

        it('handles tool_call without id', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        name: 'do_thing',
                        arguments: { x: 1 },
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')
            expect(result[0].tool_calls![0].id).toBeUndefined()
            expect(result[0].tool_calls![0].function.name).toBe('do_thing')
        })

        it('handles tool_call without arguments', () => {
            const message = {
                role: 'assistant',
                parts: [{ type: 'tool_call', id: 'call_1', name: 'no_args' }],
            }

            const result = normalizeMessage(message, 'user')
            expect(result[0].tool_calls![0].function.arguments).toEqual({})
        })

        it('normalizes role aliases', () => {
            const message = {
                role: 'human',
                parts: [{ type: 'text', content: 'Hi' }],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([{ role: 'user', content: 'Hi' }])
        })

        it('normalizes tool_call_response parts into tool messages', () => {
            const message = {
                role: 'user',
                parts: [
                    {
                        type: 'tool_call_response',
                        id: 'call_abc',
                        name: 'get_weather',
                        result: 'Sunny, 25°C',
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                { role: 'tool', content: 'Sunny, 25°C', tool_call_id: 'call_abc' },
            ])
        })

        it('stringifies non-string tool_call_response results', () => {
            const message = {
                role: 'user',
                parts: [
                    {
                        type: 'tool_call_response',
                        id: 'call_1',
                        name: 'get_data',
                        result: { temperature: 25, unit: 'C' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'tool',
                    content: '{"temperature":25,"unit":"C"}',
                    tool_call_id: 'call_1',
                },
            ])
        })

        it('parses stringified JSON tool_call arguments', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: '{"latitude":45.5,"longitude":-73.5}',
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { latitude: 45.5, longitude: -73.5 },
                            },
                        },
                    ],
                },
            ])
        })

        it('handles a full tool-use conversation', () => {
            const messages = [
                {
                    role: 'assistant',
                    parts: [
                        {
                            type: 'tool_call',
                            id: 'call_1',
                            name: 'get_weather',
                            arguments: '{"location":"Montreal"}',
                        },
                    ],
                    finish_reason: 'tool_call',
                },
                {
                    role: 'user',
                    parts: [
                        {
                            type: 'tool_call_response',
                            id: 'call_1',
                            name: 'get_weather',
                            result: '-10°C, partly cloudy',
                        },
                    ],
                },
            ]

            const result = normalizeMessages(messages, 'user')

            expect(result).toEqual([
                {
                    role: 'assistant',
                    finish_reason: 'tool_call',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: { name: 'get_weather', arguments: { location: 'Montreal' } },
                        },
                    ],
                },
                {
                    role: 'tool',
                    content: '-10°C, partly cloudy',
                    tool_call_id: 'call_1',
                },
            ])
        })

        it('handles empty parts array', () => {
            const message = {
                role: 'assistant',
                parts: [],
            }

            expect(normalizeMessage(message, 'user')).toEqual([{ role: 'assistant', content: '' }])
        })
    })

    describe('getSessionID', () => {
        const baseEvent = (overrides: Partial<LLMTraceEvent> = {}): LLMTraceEvent => ({
            id: 'event-id',
            event: '$ai_span',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
            ...overrides,
        })

        const baseTrace = (events: LLMTraceEvent[]): LLMTrace => ({
            id: 'trace-id',
            createdAt: '2024-01-01T00:00:00Z',
            distinctId: 'distinct-id',
            person: {
                uuid: 'person-id',
                created_at: '2024-01-01T00:00:00Z',
                properties: {},
                distinct_id: 'distinct-id',
            },
            events,
        })

        it('returns the direct session id when the event has one', () => {
            const event = baseEvent({
                properties: {
                    $session_id: 'session-123',
                },
            })

            expect(getSessionID(event)).toEqual('session-123')
        })

        it('derives session id from children when $ai_trace lacks direct value', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
                properties: {},
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-abc' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toEqual('session-abc')
        })

        it('returns null when child session ids conflict', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-def' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toBeNull()
        })

        it('uses consistent child session id for pseudo traces', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-xyz' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toEqual('session-xyz')
        })

        it('returns null for pseudo traces with mixed session ids', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-abc' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toBeNull()
        })
    })

    describe('costContextFromProperties', () => {
        it('returns undefined when $ai_total_cost_usd is absent', () => {
            expect(costContextFromProperties({})).toBeUndefined()
        })

        it('returns undefined when $ai_total_cost_usd is not a number', () => {
            expect(costContextFromProperties({ $ai_total_cost_usd: 'invalid' })).toBeUndefined()
        })

        it('maps all cost properties', () => {
            const props = {
                $ai_input_cost_usd: 0.01,
                $ai_output_cost_usd: 0.02,
                $ai_request_cost_usd: 0.003,
                $ai_web_search_cost_usd: 0.015,
                $ai_total_cost_usd: 0.048,
            }
            expect(costContextFromProperties(props)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('leaves optional cost fields as undefined when absent', () => {
            const props = { $ai_total_cost_usd: 0.05 }
            const ctx = costContextFromProperties(props)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
            expect(ctx && ctx.outputCost).toBeUndefined()
            expect(ctx && ctx.requestCost).toBeUndefined()
            expect(ctx && ctx.webSearchCost).toBeUndefined()
        })
    })

    describe('costContextFromTrace', () => {
        it('returns undefined when totalCost is undefined', () => {
            expect(costContextFromTrace({})).toBeUndefined()
        })

        it('maps all trace cost fields', () => {
            const trace = {
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            }
            expect(costContextFromTrace(trace)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('handles trace with only totalCost', () => {
            const trace = { totalCost: 0.05 }
            const ctx = costContextFromTrace(trace)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
        })
    })

    describe('hasCostBreakdown', () => {
        it('returns false when only totalCost is set', () => {
            expect(hasCostBreakdown({ totalCost: 0.05 })).toBe(false)
        })

        it('returns true when inputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, inputCost: 0.01 })).toBe(true)
        })

        it('returns true when outputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, outputCost: 0.02 })).toBe(true)
        })

        it('returns true when requestCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0.003 })).toBe(true)
        })

        it('returns false when requestCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0 })).toBe(false)
        })

        it('returns true when webSearchCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0.01 })).toBe(true)
        })

        it('returns false when webSearchCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0 })).toBe(false)
        })

        it('returns true when inputCost is zero (zero is still a valid breakdown)', () => {
            expect(hasCostBreakdown({ totalCost: 0, inputCost: 0 })).toBe(true)
        })
    })
})
