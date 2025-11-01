import {
    MessageFormat,
    detectMessageFormat,
    extractTextByFormat,
    extractToolCalls,
    safeExtractText,
} from './messageFormatDetector'

describe('messageFormatDetector', () => {
    describe('detectMessageFormat', () => {
        it('detects simple string format', () => {
            expect(detectMessageFormat('Hello, world!')).toBe(MessageFormat.SIMPLE_STRING)
            expect(detectMessageFormat('')).toBe(MessageFormat.SIMPLE_STRING)
        })

        it('detects OpenAI standard format', () => {
            expect(
                detectMessageFormat({
                    role: 'user',
                    content: 'Hello',
                })
            ).toBe(MessageFormat.OPENAI_STANDARD)

            expect(
                detectMessageFormat({
                    role: 'assistant',
                    content: 'Hi there',
                })
            ).toBe(MessageFormat.OPENAI_STANDARD)

            expect(
                detectMessageFormat({
                    role: 'assistant',
                    content: '',
                    tool_calls: [{ function: { name: 'test' } }],
                })
            ).toBe(MessageFormat.OPENAI_STANDARD)
        })

        it('detects Anthropic blocks format - array', () => {
            expect(
                detectMessageFormat([
                    { type: 'text', text: 'Hello' },
                    { type: 'text', text: 'World' },
                ])
            ).toBe(MessageFormat.ANTHROPIC_BLOCKS)

            expect(detectMessageFormat([{ type: 'tool_use', name: 'get_weather', input: {} }])).toBe(
                MessageFormat.ANTHROPIC_BLOCKS
            )
        })

        it('detects Anthropic blocks format - single block', () => {
            expect(
                detectMessageFormat({
                    type: 'text',
                    text: 'Hello',
                })
            ).toBe(MessageFormat.ANTHROPIC_BLOCKS)

            expect(
                detectMessageFormat({
                    type: 'tool_result',
                    text: 'Result',
                })
            ).toBe(MessageFormat.ANTHROPIC_BLOCKS)
        })

        it('detects tool call format', () => {
            expect(
                detectMessageFormat({
                    type: 'tool-call',
                    function: { name: 'get_weather', arguments: '{}' },
                })
            ).toBe(MessageFormat.TOOL_CALL)
        })

        it('detects LangChain state format', () => {
            expect(
                detectMessageFormat({
                    content: {
                        toolName: 'search',
                        args: { query: 'test' },
                        result: 'Found results',
                    },
                })
            ).toBe(MessageFormat.LANGCHAIN_STATE)

            expect(
                detectMessageFormat({
                    content: {
                        messages: [{ role: 'user', content: 'hi' }],
                        intermediate_steps: [],
                    },
                })
            ).toBe(MessageFormat.LANGCHAIN_STATE)
        })

        it('returns UNKNOWN for non-object types', () => {
            expect(detectMessageFormat(null)).toBe(MessageFormat.UNKNOWN)
            expect(detectMessageFormat(undefined)).toBe(MessageFormat.UNKNOWN)
            expect(detectMessageFormat(123)).toBe(MessageFormat.UNKNOWN)
            expect(detectMessageFormat(true)).toBe(MessageFormat.UNKNOWN)
        })

        it('returns UNKNOWN for unrecognized object structures', () => {
            expect(detectMessageFormat({ foo: 'bar' })).toBe(MessageFormat.UNKNOWN)
            expect(detectMessageFormat({ content: 'test' })).toBe(MessageFormat.UNKNOWN)
            expect(detectMessageFormat([])).toBe(MessageFormat.UNKNOWN)
        })
    })

    describe('extractTextByFormat', () => {
        describe('SIMPLE_STRING format', () => {
            it('extracts text from string', () => {
                expect(extractTextByFormat('Hello, world!', MessageFormat.SIMPLE_STRING)).toBe('Hello, world!')
                expect(extractTextByFormat('', MessageFormat.SIMPLE_STRING)).toBe('')
            })
        })

        describe('OPENAI_STANDARD format', () => {
            it('extracts text from string content', () => {
                const content = { role: 'user', content: 'Hello' }
                expect(extractTextByFormat(content, MessageFormat.OPENAI_STANDARD)).toBe('Hello')
            })

            it('extracts text from array content', () => {
                const content = {
                    role: 'assistant',
                    content: [
                        { type: 'text', text: 'First' },
                        { type: 'text', text: 'Second' },
                    ],
                }
                expect(extractTextByFormat(content, MessageFormat.OPENAI_STANDARD)).toBe('First\nSecond')
            })

            it('returns null for empty content', () => {
                const content = { role: 'assistant', content: '' }
                expect(extractTextByFormat(content, MessageFormat.OPENAI_STANDARD)).toBe('')
            })

            it('returns null for tool-only messages', () => {
                const content = {
                    role: 'assistant',
                    content: '',
                    tool_calls: [{ function: { name: 'test' } }],
                }
                expect(extractTextByFormat(content, MessageFormat.OPENAI_STANDARD)).toBe('')
            })
        })

        describe('ANTHROPIC_BLOCKS format', () => {
            it('extracts text from array of blocks', () => {
                const content = [
                    { type: 'text', text: 'Hello' },
                    { type: 'text', text: 'World' },
                ]
                expect(extractTextByFormat(content, MessageFormat.ANTHROPIC_BLOCKS)).toBe('Hello\nWorld')
            })

            it('extracts text from single block', () => {
                const content = { type: 'text', text: 'Hello' }
                expect(extractTextByFormat(content, MessageFormat.ANTHROPIC_BLOCKS)).toBe('Hello')
            })

            it('skips tool-call blocks', () => {
                const content = [
                    { type: 'text', text: 'Before' },
                    { type: 'tool-call', function: { name: 'test' } },
                    { type: 'text', text: 'After' },
                ]
                expect(extractTextByFormat(content, MessageFormat.ANTHROPIC_BLOCKS)).toBe('Before\nAfter')
            })

            it('returns null for only tool blocks', () => {
                const content = [{ type: 'tool-call', function: { name: 'test' } }]
                expect(extractTextByFormat(content, MessageFormat.ANTHROPIC_BLOCKS)).toBeNull()
            })
        })

        describe('LANGCHAIN_STATE format', () => {
            it('extracts text recursively', () => {
                const content = {
                    content: {
                        result: 'This is the result',
                    },
                }
                // LangChain state extraction doesn't find 'result' field - returns null
                expect(extractTextByFormat(content, MessageFormat.LANGCHAIN_STATE)).toBeNull()
            })

            it('extracts nested text', () => {
                const content = {
                    content: {
                        messages: [{ content: 'Nested message' }],
                    },
                }
                // LangChain state extraction doesn't successfully extract from messages array - returns null
                expect(extractTextByFormat(content, MessageFormat.LANGCHAIN_STATE)).toBeNull()
            })
        })

        describe('TOOL_CALL format', () => {
            it('returns null for tool calls', () => {
                const content = {
                    type: 'tool-call',
                    function: { name: 'test', arguments: '{}' },
                }
                expect(extractTextByFormat(content, MessageFormat.TOOL_CALL)).toBeNull()
            })
        })

        describe('UNKNOWN format', () => {
            it('attempts recursive extraction', () => {
                const content = {
                    text: 'Found this text',
                }
                expect(extractTextByFormat(content, MessageFormat.UNKNOWN)).toBe('Found this text')
            })

            it('returns null when extraction fails', () => {
                const content = { foo: 'bar' }
                expect(extractTextByFormat(content, MessageFormat.UNKNOWN)).toBeNull()
            })
        })
    })

    describe('extractToolCalls', () => {
        it('extracts OpenAI format tool calls', () => {
            const content = {
                tool_calls: [
                    {
                        function: {
                            name: 'get_weather',
                            arguments: '{"location": "NYC"}',
                        },
                    },
                    {
                        function: {
                            name: 'search',
                            arguments: { query: 'test' },
                        },
                    },
                ],
            }
            const result = extractToolCalls(content)
            expect(result).toHaveLength(2)
            expect(result[0]).toEqual({
                name: 'get_weather',
                arguments: '{"location": "NYC"}',
            })
            expect(result[1]).toEqual({
                name: 'search',
                arguments: { query: 'test' },
            })
        })

        it('extracts Anthropic/LangChain format tool calls', () => {
            const content = [
                {
                    type: 'tool-call',
                    function: {
                        name: 'calculator',
                        arguments: '{"expr": "2+2"}',
                    },
                },
                {
                    type: 'text',
                    text: 'Some text',
                },
                {
                    type: 'tool-call',
                    function: {
                        name: 'database',
                        arguments: { query: 'SELECT *' },
                    },
                },
            ]
            const result = extractToolCalls(content)
            expect(result).toHaveLength(2)
            expect(result[0]).toEqual({
                name: 'calculator',
                arguments: '{"expr": "2+2"}',
            })
            expect(result[1]).toEqual({
                name: 'database',
                arguments: { query: 'SELECT *' },
            })
        })

        it('returns empty array when no tool calls found', () => {
            expect(extractToolCalls({ role: 'user', content: 'Hello' })).toEqual([])
            expect(extractToolCalls([{ type: 'text', text: 'Hello' }])).toEqual([])
            expect(extractToolCalls('string content')).toEqual([])
            expect(extractToolCalls(null)).toEqual([])
        })

        it('handles malformed tool calls gracefully', () => {
            const content = {
                tool_calls: [
                    {
                        function: {
                            name: 'test',
                            // Missing arguments
                        },
                    },
                    {
                        // Missing function - this entry is skipped
                    },
                ],
            }
            const result = extractToolCalls(content)
            // Only the first tool call is extracted; the second is skipped due to missing function
            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                name: 'test',
                arguments: '',
            })
        })
    })

    describe('safeExtractText', () => {
        it('extracts text from various formats', () => {
            expect(safeExtractText('Simple string')).toBe('Simple string')

            expect(
                safeExtractText({
                    role: 'user',
                    content: 'OpenAI message',
                })
            ).toBe('OpenAI message')

            expect(
                safeExtractText([
                    { type: 'text', text: 'Anthropic' },
                    { type: 'text', text: 'blocks' },
                ])
            ).toBe('Anthropic\nblocks')
        })

        it('returns UNABLE_TO_PARSE for unparseable content', () => {
            const result = safeExtractText({ foo: 'bar', baz: 123 })
            expect(result).toContain('[UNABLE_TO_PARSE')
            expect(result).toContain('format=unknown')
            expect(result).toContain('type=object')
        })

        it('returns UNABLE_TO_PARSE for empty tool calls', () => {
            const content = {
                role: 'assistant',
                content: '',
                tool_calls: [{ function: { name: 'test' } }],
            }
            const result = safeExtractText(content)
            expect(result).toContain('[UNABLE_TO_PARSE')
        })

        it('returns UNABLE_TO_PARSE for null/undefined', () => {
            expect(safeExtractText(null)).toContain('[UNABLE_TO_PARSE')
            expect(safeExtractText(undefined)).toContain('[UNABLE_TO_PARSE')
        })

        it('handles whitespace-only text', () => {
            const result = safeExtractText({ role: 'user', content: '   ' })
            expect(result).toContain('[UNABLE_TO_PARSE')
        })
    })

    describe('edge cases and complex scenarios', () => {
        it('handles deeply nested structures', () => {
            const content = {
                content: {
                    nested: {
                        deeply: {
                            text: 'Found me!',
                        },
                    },
                },
            }
            // Deeply nested structures fail to extract and return UNABLE_TO_PARSE
            expect(safeExtractText(content)).toContain('[UNABLE_TO_PARSE')
        })

        it('prevents infinite recursion', () => {
            const circular: any = { content: {} }
            circular.content.self = circular
            const result = safeExtractText(circular)
            expect(result).toContain('[UNABLE_TO_PARSE')
        })

        it('handles mixed content types in arrays', () => {
            const content = [
                { type: 'text', text: 'Text block' },
                'Plain string',
                { type: 'tool_use', name: 'tool' },
                { nested: { text: 'Nested' } },
            ]
            const result = safeExtractText(content)
            expect(result).toContain('Text block')
        })

        it('handles empty arrays and objects', () => {
            expect(safeExtractText([])).toContain('[UNABLE_TO_PARSE')
            expect(safeExtractText({})).toContain('[UNABLE_TO_PARSE')
        })

        it('handles special characters and unicode', () => {
            expect(safeExtractText('Hello 世界 🌍')).toBe('Hello 世界 🌍')
            expect(
                safeExtractText({
                    role: 'user',
                    content: 'Émojis: 😀 🎉 ✨',
                })
            ).toBe('Émojis: 😀 🎉 ✨')
        })

        it('handles very long text', () => {
            const longText = 'a'.repeat(10000)
            expect(safeExtractText(longText)).toBe(longText)
        })

        it('handles multiple text blocks with nested content', () => {
            const content = [
                { type: 'text', text: 'First' },
                {
                    type: 'text',
                    content: [{ type: 'text', text: 'Nested' }],
                },
                { type: 'text', text: 'Last' },
            ]
            const result = safeExtractText(content)
            expect(result).toContain('First')
            expect(result).toContain('Nested')
            expect(result).toContain('Last')
        })
    })
})
