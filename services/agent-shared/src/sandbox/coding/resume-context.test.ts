import { describe, expect, it } from 'vitest'

import type { ConversationMessage } from '../../spec/spec'
import { buildResumePrompt, formatConversationForResume } from './resume-context'

const conversation: ConversationMessage[] = [
    { role: 'user', content: 'list the files', timestamp: 1 },
    {
        role: 'assistant',
        content: [
            { type: 'text', text: 'Listed the files.' },
            { type: 'toolCall', id: 't1', name: 'Bash', arguments: { command: 'ls' } },
        ],
        timestamp: 2,
    },
    {
        role: 'toolResult',
        toolCallId: 't1',
        toolName: 'Bash',
        content: [{ type: 'text', text: 'file.txt' }],
        isError: false,
        timestamp: 3,
    },
]

describe('formatConversationForResume', () => {
    it('formats user/assistant text and folds tool results into the assistant turn', () => {
        const history = formatConversationForResume(conversation)
        expect(history).toBe(
            '**User**: list the files\n\n' +
                '**Assistant**: Listed the files.\n\n' +
                '**Assistant (tools)**:\n  - Bash → file.txt'
        )
    })

    it('returns null for an empty conversation', () => {
        expect(formatConversationForResume([])).toBeNull()
    })

    it('handles structured user content and skips empty turns', () => {
        const history = formatConversationForResume([
            { role: 'user', content: [{ type: 'text', text: 'hello' }], timestamp: 1 },
            { role: 'assistant', content: [], timestamp: 2 },
        ])
        expect(history).toBe('**User**: hello')
    })

    it('truncates oversized tool results', () => {
        const history = formatConversationForResume([
            {
                role: 'assistant',
                content: [{ type: 'toolCall', id: 't1', name: 'Bash', arguments: {} }],
                timestamp: 1,
            },
            {
                role: 'toolResult',
                toolCallId: 't1',
                toolName: 'Bash',
                content: [{ type: 'text', text: 'x'.repeat(5000) }],
                isError: false,
                timestamp: 2,
            },
        ])
        expect(history).toContain('...(truncated)')
        expect(history!.length).toBeLessThan(2500)
    })

    it('drops the oldest turns when over the char budget, noting the omission', () => {
        const long: ConversationMessage[] = []
        for (let i = 0; i < 60; i++) {
            long.push({ role: 'user', content: `question ${i} ${'pad '.repeat(700)}`, timestamp: i * 2 })
            long.push({ role: 'assistant', content: [{ type: 'text', text: `answer ${i}` }], timestamp: i * 2 + 1 })
        }
        const history = formatConversationForResume(long)
        expect(history).toContain('earlier turns omitted')
        expect(history).toContain('answer 59')
        expect(history).not.toContain('question 0 ')
        expect(history!.length).toBeLessThanOrEqual(110_000)
    })
})

describe('buildResumePrompt', () => {
    it('wraps history + new message in the harness resume preamble', () => {
        const prompt = buildResumePrompt('**User**: hi', 'do step two')
        // Matches the harness's own resume wording so its resume-context
        // detection recognizes this turn if native resume lands later.
        expect(prompt).toContain('You are resuming a previous conversation')
        expect(prompt).toContain('Here is the conversation history from the previous session:')
        expect(prompt).toContain('**User**: hi')
        expect(prompt).toContain('The user has sent a new message:')
        expect(prompt).toContain('do step two')
        expect(prompt.indexOf('**User**: hi')).toBeLessThan(prompt.indexOf('do step two'))
    })
})
