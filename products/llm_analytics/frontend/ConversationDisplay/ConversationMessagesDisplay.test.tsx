import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
