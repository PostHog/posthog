import type { ConversationItem, RenderItem, TurnContext } from './buildConversationItems'
import {
    applyHighlights,
    clearHighlights,
    escapeRegExp,
    extractSearchableText,
    findItemElement,
    findMatchesInItems,
    findRangesInItem,
    highlightsSupported,
} from './conversationSearch'

function turnContext(): TurnContext {
    return { toolCalls: new Map(), childItems: new Map(), turnCancelled: false, turnComplete: true }
}

function sessionUpdate(update: RenderItem, id = 'su-1'): ConversationItem {
    return { type: 'session_update', id, update, turnContext: turnContext() }
}

function userMessage(content: string, id = 'um-1'): ConversationItem {
    return { type: 'user_message', id, content, timestamp: 0 }
}

describe('conversationSearch', () => {
    describe('extractSearchableText', () => {
        it('extracts user message content', () => {
            expect(extractSearchableText(userMessage('hello world'))).toBe('hello world')
        })

        it('extracts agent message text chunk', () => {
            const item = sessionUpdate({
                sessionUpdate: 'agent_message_chunk',
                content: { type: 'text', text: 'agent reply' },
            })
            expect(extractSearchableText(item)).toBe('agent reply')
        })

        it('extracts agent thought text chunk', () => {
            const item = sessionUpdate({
                sessionUpdate: 'agent_thought_chunk',
                content: { type: 'text', text: 'thinking...' },
            })
            expect(extractSearchableText(item)).toBe('thinking...')
        })

        it('returns empty string for non-text agent chunks', () => {
            const item = sessionUpdate({
                sessionUpdate: 'agent_message_chunk',
                content: { type: 'image', data: 'base64data', mimeType: 'image/png' },
            })
            expect(extractSearchableText(item)).toBe('')
        })

        it('returns empty string for tool calls', () => {
            const item = sessionUpdate({
                sessionUpdate: 'tool_call',
                toolCallId: 'tc-1',
                title: 'Read file',
            })
            expect(extractSearchableText(item)).toBe('')
        })

        it('extracts console message', () => {
            const item = sessionUpdate({ sessionUpdate: 'console', level: 'info', message: 'console output' })
            expect(extractSearchableText(item)).toBe('console output')
        })

        it('extracts error message', () => {
            const item = sessionUpdate({ sessionUpdate: 'error', errorType: 'FatalError', message: 'something broke' })
            expect(extractSearchableText(item)).toBe('something broke')
        })

        it('extracts status text', () => {
            const item = sessionUpdate({ sessionUpdate: 'status', status: 'running' })
            expect(extractSearchableText(item)).toBe('running')
        })

        it('extracts task notification summary', () => {
            const item = sessionUpdate({
                sessionUpdate: 'task_notification',
                taskId: 't1',
                status: 'completed',
                summary: 'task done',
                outputFile: '/tmp/out',
            })
            expect(extractSearchableText(item)).toBe('task done')
        })

        it('returns empty string for progress groups', () => {
            const item = sessionUpdate({
                sessionUpdate: 'progress_group',
                steps: [{ key: 's1', status: 'completed', label: 'Cloning repo' }],
                isActive: false,
            })
            expect(extractSearchableText(item)).toBe('')
        })

        it('returns empty string for compact boundaries', () => {
            const item = sessionUpdate({ sessionUpdate: 'compact_boundary', trigger: 'auto', preTokens: 1000 })
            expect(extractSearchableText(item)).toBe('')
        })

        it('joins shell command with stdout and stderr', () => {
            const item: ConversationItem = {
                type: 'user_shell_execute',
                id: '10',
                command: 'ls -la',
                cwd: '/tmp',
                result: { stdout: 'file.txt', stderr: 'warning', exitCode: 0 },
            }
            expect(extractSearchableText(item)).toBe('ls -la file.txt warning')
        })

        it('returns just the command when shell execute has no result', () => {
            const item: ConversationItem = { type: 'user_shell_execute', id: '11', command: 'echo hi', cwd: '/tmp' }
            expect(extractSearchableText(item)).toBe('echo hi  ')
        })

        it.each([
            [undefined, 'Interrupted by user'],
            ['some_other_reason', 'Interrupted by user'],
            ['moving_to_worktree', 'Paused while worktree is focused'],
        ])('mirrors the rendered copy for turn_cancelled with reason %s', (interruptReason, expected) => {
            const item: ConversationItem = { type: 'turn_cancelled', id: '12', interruptReason }
            expect(extractSearchableText(item)).toBe(expected)
        })

        it('extracts queued message content', () => {
            const item: ConversationItem = {
                type: 'queued',
                id: '14',
                message: { id: 'q1', content: 'queued text', queuedAt: 0 },
            }
            expect(extractSearchableText(item)).toBe('queued text')
        })

        it.each(['git_action', 'skill_button_action', 'git_action_result'] as const)(
            'returns empty string for %s items',
            (type) => {
                const item = {
                    type,
                    id: 'x',
                    actionType: 'commit',
                    buttonId: 'btn',
                    turnId: 't',
                } as unknown as ConversationItem
                expect(extractSearchableText(item)).toBe('')
            }
        )
    })

    describe('escapeRegExp', () => {
        it.each([
            ['a.b', 'a\\.b'],
            ['(x)', '\\(x\\)'],
            ['a+b*c?', 'a\\+b\\*c\\?'],
            ['[1]{2}', '\\[1\\]\\{2\\}'],
            ['a|b^$\\', 'a\\|b\\^\\$\\\\'],
            ['plain text', 'plain text'],
        ])('escapes %s', (input, expected) => {
            expect(escapeRegExp(input)).toBe(expected)
        })
    })

    describe('findMatchesInItems', () => {
        const items: ConversationItem[] = [
            userMessage('fix the Bug in the bug tracker', 'um-1'),
            sessionUpdate({ sessionUpdate: 'tool_call', toolCallId: 'tc-1', title: 'bug hunt' }, 'su-1'),
            sessionUpdate(
                { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'BUG fixed' } },
                'su-2'
            ),
        ]

        it('returns no matches for an empty query', () => {
            expect(findMatchesInItems(items, '')).toEqual([])
        })

        it('returns no matches when nothing matches', () => {
            expect(findMatchesInItems(items, 'zebra')).toEqual([])
        })

        it('finds case-insensitive matches across items with per-item occurrence counts', () => {
            expect(findMatchesInItems(items, 'bug')).toEqual([
                { itemIndex: 0, itemId: 'um-1', occurrenceInItem: 0 },
                { itemIndex: 0, itemId: 'um-1', occurrenceInItem: 1 },
                { itemIndex: 2, itemId: 'su-2', occurrenceInItem: 0 },
            ])
        })

        it('skips tool call items even when their title matches', () => {
            const matches = findMatchesInItems(items, 'hunt')
            expect(matches).toEqual([])
        })

        it('treats regex special characters literally', () => {
            const withDots = [userMessage('call a.b() now', 'um-2')]
            expect(findMatchesInItems(withDots, 'a.b()')).toEqual([
                { itemIndex: 0, itemId: 'um-2', occurrenceInItem: 0 },
            ])
            expect(findMatchesInItems([userMessage('aXb', 'um-3')], 'a.b')).toEqual([])
        })
    })

    describe('findItemElement', () => {
        it('finds the element carrying the matching data attribute', () => {
            const container = document.createElement('div')
            container.innerHTML =
                '<div data-conversation-item-id="item-1">one</div><div data-conversation-item-id="item-2">two</div>'
            expect(findItemElement(container, 'item-2')?.textContent).toBe('two')
        })

        it('returns null when the item is not in the DOM', () => {
            const container = document.createElement('div')
            expect(findItemElement(container, 'missing')).toBeNull()
        })

        it('escapes ids that contain CSS-significant characters', () => {
            const container = document.createElement('div')
            const el = document.createElement('div')
            el.setAttribute('data-conversation-item-id', 'turn-1"]x')
            el.textContent = 'tricky'
            container.appendChild(el)
            expect(findItemElement(container, 'turn-1"]x')?.textContent).toBe('tricky')
        })
    })

    describe('findRangesInItem', () => {
        function itemEl(html: string): HTMLElement {
            const el = document.createElement('div')
            el.innerHTML = html
            document.body.appendChild(el)
            return el
        }

        afterEach(() => {
            document.body.innerHTML = ''
        })

        it('returns ranges covering each occurrence in a single text node', () => {
            const el = itemEl('the bug and the Bug')
            const ranges = findRangesInItem(el, 'bug')
            expect(ranges.map((r) => r.toString())).toEqual(['bug', 'Bug'])
        })

        it('finds occurrences across nested elements', () => {
            const el = itemEl('<p>first bug</p><pre><code>second bug</code></pre>')
            const ranges = findRangesInItem(el, 'bug')
            expect(ranges).toHaveLength(2)
            expect(ranges.every((r) => r.toString() === 'bug')).toBe(true)
        })

        it('returns offsets relative to the containing text node', () => {
            const el = itemEl('xx bug')
            const [range] = findRangesInItem(el, 'bug')
            expect(range.startOffset).toBe(3)
            expect(range.endOffset).toBe(6)
        })

        it('returns no ranges for an empty query', () => {
            const el = itemEl('anything')
            expect(findRangesInItem(el, '')).toEqual([])
        })

        it('does not match text split across separate text nodes', () => {
            const el = itemEl('<span>bu</span><span>g</span>')
            expect(findRangesInItem(el, 'bug')).toEqual([])
        })
    })

    describe('highlight registry', () => {
        it('reports unsupported and degrades gracefully without the Highlight API', () => {
            // jsdom has no CSS.highlights / Highlight constructor.
            expect(highlightsSupported()).toBe(false)
            expect(() => clearHighlights()).not.toThrow()
            const container = document.createElement('div')
            container.innerHTML = '<div data-conversation-item-id="i1">bug</div>'
            const result = applyHighlights(
                container,
                'bug',
                [{ itemIndex: 0, itemId: 'i1', occurrenceInItem: 0 }],
                null
            )
            expect(result).toBeNull()
        })
    })
})
