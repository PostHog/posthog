import { formatInputMessages, formatOutputMessages } from './messageFormatter'

describe('messageFormatter', () => {
    describe('formatInputMessages', () => {
        it('formats simple string input', () => {
            const result = formatInputMessages('Hello, world!')

            expect(result.join('\n')).toContain('INPUT:')
            expect(result.join('\n')).toContain('[User input]')
            expect(result.join('\n')).toContain('Hello, world!')
        })

        it('formats array of messages', () => {
            const input = [
                { role: 'user', content: 'First message' },
                { role: 'assistant', content: 'Second message' },
            ]
            const result = formatInputMessages(input)

            expect(result.join('\n')).toContain('[1] USER')
            expect(result.join('\n')).toContain('First message')
            expect(result.join('\n')).toContain('[2] ASSISTANT')
            expect(result.join('\n')).toContain('Second message')
        })

        it('formats messages with tool calls', () => {
            const input = [
                {
                    role: 'assistant',
                    content: 'Let me check that',
                    tool_calls: [
                        {
                            function: {
                                name: 'get_weather',
                                arguments: '{"location": "NYC"}',
                            },
                        },
                    ],
                },
            ]
            const result = formatInputMessages(input)

            expect(result.join('\n')).toContain('Tool calls: 1')
            expect(result.join('\n')).toContain('get_weather(location="NYC")')
        })

        it('returns empty array for empty input', () => {
            expect(formatInputMessages([])).toEqual([])
            expect(formatInputMessages(null)).toEqual([])
            expect(formatInputMessages(undefined)).toEqual([])
        })

        it('formats Anthropic-style message arrays', () => {
            const input = [
                {
                    role: 'user',
                    content: [
                        { type: 'text', text: 'First part' },
                        { type: 'text', text: 'Second part' },
                    ],
                },
            ]
            const result = formatInputMessages(input)

            expect(result.join('\n')).toContain('First part')
            expect(result.join('\n')).toContain('Second part')
        })

        it('truncates long content with markers', () => {
            const longContent = 'a'.repeat(2000)
            const input = [{ role: 'user', content: longContent }]
            const result = formatInputMessages(input)

            const text = result.join('\n')
            expect(text).toContain('<<<TRUNCATED|')
            expect(text).toMatch(/<<<TRUNCATED\|[^|]+\|\d+>>>/)
        })
    })

    describe('formatOutputMessages', () => {
        describe('UNABLE_TO_PARSE conditional display', () => {
            it('shows text content when available', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: 'Valid response',
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('Valid response')
                expect(result.join('\n')).not.toContain('[UNABLE_TO_PARSE')
            })

            it('shows tool calls without UNABLE_TO_PARSE when no text content', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: '',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'get_weather',
                                        arguments: { location: 'SF' },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('Tool calls: 1')
                expect(text).toContain('get_weather')
                expect(text).not.toContain('[UNABLE_TO_PARSE')
                expect(text).not.toContain('[empty response]')
            })

            it('shows tool calls from content array without UNABLE_TO_PARSE', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: [
                                {
                                    type: 'tool-call',
                                    function: {
                                        name: 'calculator',
                                        arguments: { expr: '2+2' },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('Tool calls: 1')
                expect(text).toContain('calculator')
                expect(text).not.toContain('[UNABLE_TO_PARSE')
            })

            it('shows both text and tool calls when both present', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: 'Let me check that for you',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'search',
                                        arguments: { query: 'test' },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('Let me check that for you')
                expect(text).toContain('Tool calls: 1')
                expect(text).toContain('search')
                expect(text).not.toContain('[UNABLE_TO_PARSE')
            })

            it('shows UNABLE_TO_PARSE only when no text and no tool calls', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: { foo: 'bar', baz: 123 },
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('[UNABLE_TO_PARSE')
            })

            it('shows UNABLE_TO_PARSE when content is empty string and no tool calls', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: '',
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                // Empty string returns UNABLE_TO_PARSE because safeExtractText considers it unparseable
                expect(text).toContain('[UNABLE_TO_PARSE')
            })

            it('handles multiple choices with mixed content', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: 'Valid text',
                        },
                    },
                    {
                        message: {
                            role: 'assistant',
                            content: '',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'tool',
                                        arguments: {},
                                    },
                                },
                            ],
                        },
                    },
                    {
                        message: {
                            role: 'assistant',
                            content: '',
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('Valid text')
                expect(text).toContain('Tool calls: 1')
                // The third message with empty content shows UNABLE_TO_PARSE
                expect(text).toContain('[UNABLE_TO_PARSE')
            })
        })

        describe('tool call formatting', () => {
            it('formats tool calls with string arguments', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'get_weather',
                                        arguments: '{"location": "NYC", "unit": "F"}',
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('get_weather(location="NYC", unit="F")')
            })

            it('formats tool calls with object arguments', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'calculator',
                                        arguments: { operation: 'add', a: 2, b: 3 },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('calculator(')
                expect(text).toContain('operation="add"')
                expect(text).toContain('a=2')
                expect(text).toContain('b=3')
            })

            it('formats tool calls with no arguments', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'get_current_time',
                                        arguments: '',
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('get_current_time()')
            })

            it('formats multiple tool calls', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'tool1',
                                        arguments: { arg: 1 },
                                    },
                                },
                                {
                                    function: {
                                        name: 'tool2',
                                        arguments: { arg: 2 },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('Tool calls: 2')
                expect(text).toContain('tool1(arg=1)')
                expect(text).toContain('tool2(arg=2)')
            })

            it('handles malformed tool call arguments', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            tool_calls: [
                                {
                                    function: {
                                        name: 'test',
                                        arguments: 'not valid json {',
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('test(not valid json {)')
            })
        })

        describe('message role handling', () => {
            it('labels tool messages specially', () => {
                const choices = [
                    {
                        role: 'tool',
                        content: 'Tool result content',
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('[1] TOOL RESULT')
                expect(result.join('\n')).toContain('Tool result content')
            })

            it('handles standard assistant role', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: 'Response',
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('[1] ASSISTANT')
            })

            it('handles unknown roles', () => {
                const choices = [
                    {
                        role: 'custom_agent',
                        content: 'Custom response',
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('[1] CUSTOM_AGENT')
            })
        })

        describe('different output formats', () => {
            it('handles simple string output', () => {
                const result = formatOutputMessages('Simple response', null)

                expect(result.join('\n')).toContain('OUTPUT:')
                expect(result.join('\n')).toContain('Simple response')
            })

            it('handles xai-style wrapped choices', () => {
                const output = {
                    choices: [
                        {
                            message: {
                                role: 'assistant',
                                content: 'Response from xai',
                            },
                        },
                    ],
                }
                const result = formatOutputMessages(null, output)

                expect(result.join('\n')).toContain('Response from xai')
            })

            it('handles direct choices array', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: 'Direct choice',
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('Direct choice')
            })

            it('handles string choice items', () => {
                const choices = ['String choice 1', 'String choice 2']
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('String choice 1')
                expect(result.join('\n')).toContain('String choice 2')
            })

            it('returns empty array for no output', () => {
                const result = formatOutputMessages(null, null)
                expect(result).toEqual([])
            })
        })

        describe('content truncation', () => {
            it('truncates long output content', () => {
                const longContent = 'x'.repeat(2000)
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: longContent,
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('<<<TRUNCATED|')
                expect(text).toMatch(/<<<TRUNCATED\|[^|]+\|\d+>>>/)
            })
        })

        describe('LangChain-style content', () => {
            it('handles tool-call content blocks inline', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: [
                                {
                                    content: {
                                        toolName: 'database_query',
                                        args: { query: 'SELECT *' },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                const text = result.join('\n')
                expect(text).toContain('database_query(query="SELECT *")')
            })

            it('handles tool-result content blocks', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: [
                                {
                                    content: {
                                        toolName: 'search',
                                        result: { found: 10 },
                                    },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                // Tool result shows as tool call, not special "[Tool result:]" format
                expect(result.join('\n')).toContain('search()')
            })
        })

        describe('Anthropic tool_use format', () => {
            it('handles tool_use type blocks', () => {
                const choices = [
                    {
                        message: {
                            role: 'assistant',
                            content: [
                                {
                                    type: 'tool_use',
                                    name: 'get_stock_price',
                                    input: { ticker: 'AAPL' },
                                },
                            ],
                        },
                    },
                ]
                const result = formatOutputMessages(null, choices)

                expect(result.join('\n')).toContain('[Tool use: get_stock_price]')
            })
        })
    })

    describe('edge cases and real-world scenarios', () => {
        it('handles mixed text and tool blocks', () => {
            const choices = [
                {
                    message: {
                        role: 'assistant',
                        content: [
                            { type: 'text', text: 'Let me help you with that.' },
                            {
                                type: 'tool-call',
                                function: {
                                    name: 'helper',
                                    arguments: {},
                                },
                            },
                            { type: 'text', text: 'Processing...' },
                        ],
                    },
                },
            ]
            const result = formatOutputMessages(null, choices)

            const text = result.join('\n')
            expect(text).toContain('Let me help you with that.')
            expect(text).toContain('Processing...')
            expect(text).toContain('Tool calls: 1')
        })

        it('handles empty content array', () => {
            const choices = [
                {
                    message: {
                        role: 'assistant',
                        content: [],
                    },
                },
            ]
            const result = formatOutputMessages(null, choices)

            // Empty array is considered UNKNOWN format with no extractable text
            expect(result.join('\n')).toContain('[UNABLE_TO_PARSE')
        })

        it('handles deeply nested structures', () => {
            const choices = [
                {
                    message: {
                        role: 'assistant',
                        content: {
                            nested: {
                                deeply: {
                                    text: 'Found this',
                                },
                            },
                        },
                    },
                },
            ]
            const result = formatOutputMessages(null, choices)

            // Deeply nested structures are detected as UNKNOWN format and fail to extract text
            expect(result.join('\n')).toContain('[UNABLE_TO_PARSE')
        })

        it('preserves separators between multiple messages', () => {
            const choices = [
                { message: { role: 'assistant', content: 'First' } },
                { message: { role: 'assistant', content: 'Second' } },
            ]
            const result = formatOutputMessages(null, choices)

            const text = result.join('\n')
            expect(text).toContain('First')
            expect(text).toContain('Second')
            expect(text).toContain('-'.repeat(80))
        })
    })
})
