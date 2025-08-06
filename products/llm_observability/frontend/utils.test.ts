import { AnthropicInputMessage, OpenAICompletionMessage } from './types'
import { normalizeMessage } from './utils'

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
        expect(normalizeMessage(message)).toEqual([
            {
                role: 'user',
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
        expect(normalizeMessage('foo')).toEqual([
            {
                role: 'user',
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
})
