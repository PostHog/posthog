import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { CompatMessage } from '../types'
import {
    ConversationDisplayOption,
    ConversationMessagesDisplay,
    LLMMessageDisplay,
} from './ConversationMessagesDisplay'

describe('LLMMessageDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        [
            'bracket-prefixed thinking text',
            '[Thinking: The user wants to build a todo app.]I will build a clean todo app for you!',
        ],
        [
            'bracket-prefixed tool call text',
            '[Tool Call: lov-write, Input: {"file_path":"src/pages/Index.tsx","content":"import React"}]',
        ],
        [
            'mixed thinking and tool call text',
            '[Thinking: Let me help.]Here is the answer.[Tool Call: write, Input: {"path":"index.ts"}]',
        ],
    ])('renders %s as plain text instead of empty JSON', (_label, content) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show minimal />
            </Provider>
        )
        expect(container.textContent).toContain(content)
    })

    it.each([
        ['valid JSON object', '{"key": "value"}', 'key'],
        ['valid JSON array', '[{"role": "assistant", "content": "hello"}]', 'role'],
        ['truncated JSON object', '{"key": "val', 'key'],
    ])('renders %s as JSON', (_label, content, expectedSubstring) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show minimal />
            </Provider>
        )
        expect(container.textContent).toContain(expectedSubstring)
    })

    it('renders content[].type=function with object arguments as a tool-call block', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    id: 'call_abc',
                    function: {
                        name: 'get_weather',
                        arguments: { location: 'San Francisco' },
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('get_weather')
        expect(container.textContent).toContain('call_abc')
        await waitFor(() => {
            expect(container.textContent).toContain('location')
            expect(container.textContent).toContain('San Francisco')
        })
    })

    it('renders content[].type=function with stringified JSON arguments', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'get_weather',
                        arguments: '{"location": "Berlin"}',
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('get_weather')
        await waitFor(() => {
            expect(container.textContent).toContain('location')
            expect(container.textContent).toContain('Berlin')
        })
    })

    it('renders content[].type=function with unparseable string arguments without crashing', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'broken_call',
                        arguments: '{not valid json',
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('broken_call')
        expect(container.textContent).toContain('{not valid json')
    })

    it('renders content[].type=function without an id', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'no_id_call',
                        arguments: { foo: 'bar' },
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('no_id_call')
    })

    it('renders content[].type=function with arguments: null without crashing (header only)', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    id: 'call_xyz',
                    function: {
                        name: 'no_args_tool',
                        arguments: null,
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('no_args_tool')
        expect(container.textContent).toContain('call_xyz')
        expect(container.querySelector('.react-json-view')).toBeNull()
    })

    it('renders empty-args function as header only (no JSON viewer body)', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'empty_args_tool',
                        arguments: {},
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('empty_args_tool')
        expect(container.querySelector('.react-json-view')).toBeNull()
    })

    it('preserves order across mixed text and function items in a single assistant message', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                { type: 'text', text: 'Searching now.' },
                {
                    type: 'function',
                    id: 'fs_001',
                    function: { name: 'file_search', arguments: { query: 'refund policy' } },
                },
                {
                    type: 'function',
                    id: 'mcp_002',
                    function: { name: 'mcp.fetch', arguments: '{"url":"https://example.com"}' },
                },
                { type: 'text', text: 'Done.' },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        await waitFor(() => {
            const text = container.textContent ?? ''
            expect(text).toContain('Searching now.')
            expect(text).toContain('file_search')
            expect(text).toContain('mcp.fetch')
            expect(text).toContain('Done.')
            // Ordering: text -> file_search -> mcp.fetch -> text
            const iSearching = text.indexOf('Searching now.')
            const iFileSearch = text.indexOf('file_search')
            const iMcpFetch = text.indexOf('mcp.fetch')
            const iDone = text.indexOf('Done.')
            expect(iSearching).toBeLessThan(iFileSearch)
            expect(iFileSearch).toBeLessThan(iMcpFetch)
            expect(iMcpFetch).toBeLessThan(iDone)
        })
    })
})

describe('ConversationMessagesDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const inputNormalized: CompatMessage[] = [
        { role: 'system', content: 'system input content' },
        { role: 'user', content: 'first user input content' },
        { role: 'assistant', content: 'assistant input content' },
        { role: 'user', content: 'second user input content' },
    ]
    const outputNormalized: CompatMessage[] = [{ role: 'assistant', content: 'assistant output content' }]

    it.each<[string, string, string[], string[]]>([
        [
            'expand_all',
            'expand_all',
            [
                'system input content',
                'first user input content',
                'assistant input content',
                'second user input content',
                'assistant output content',
            ],
            [],
        ],
        [
            'expand_user_only',
            'expand_user_only',
            ['first user input content', 'second user input content'],
            ['system input content', 'assistant input content', 'assistant output content'],
        ],
        [
            'collapse_except_output_and_last_input',
            'collapse_except_output_and_last_input',
            ['second user input content', 'assistant output content'],
            ['system input content', 'first user input content', 'assistant input content'],
        ],
    ])('display option %s shows/hides correct messages', (_label, displayOption, visible, hidden) => {
        render(
            <Provider>
                <ConversationMessagesDisplay
                    inputNormalized={inputNormalized}
                    outputNormalized={outputNormalized}
                    errorData={null}
                    raisedError={false}
                    displayOption={displayOption as ConversationDisplayOption}
                />
            </Provider>
        )

        for (const text of visible) {
            expect(screen.getByText(text)).toBeInTheDocument()
        }
        for (const text of hidden) {
            expect(screen.queryByText(text)).not.toBeInTheDocument()
        }
    })
})
