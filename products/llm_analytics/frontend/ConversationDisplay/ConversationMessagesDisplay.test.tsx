import '@testing-library/jest-dom'
import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { CompatMessage } from '../types'
import { LLMMessageDisplay } from './ConversationMessagesDisplay'

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
