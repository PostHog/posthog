import { act, fireEvent, render, screen } from '@testing-library/react-native'
import * as Clipboard from 'expo-clipboard'
import type { ReactElement } from 'react'
import { ActivityIndicator, ScrollView } from 'react-native'
import { setAnalyticsClient } from '@/lib/analytics'

import * as markdown from '../ChatMarkdown'
import { SessionThread } from './SessionThread'
import type { Session, SessionThreadItem, SessionToolInvocation } from './types'

// Reanimated's native worklets runtime does not exist under Jest, and its mock has no `useReducedMotion`.
jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

jest.mock('react-native-keyboard-controller', () => ({
    useReanimatedKeyboardAnimation: () => ({ height: { value: 0 } }),
}))

jest.mock('@/features/handoff/usePullRequestChecks', () => ({
    usePullRequestChecks: () => ({ status: 'unavailable', isRefreshing: false }),
}))

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))

function session(overrides: Partial<Session> = {}): Session {
    return {
        taskId: 'task-1',
        runId: 'run-1',
        title: 'Fix the chart legend',
        runStatus: 'in_progress',
        items: [],
        invocations: new Map(),
        phase: 'idle',
        history: { status: 'idle', error: null },
        isSending: false,
        isStopping: false,
        canSteer: false,
        start: async () => true,
        send: async () => true,
        answer: async () => undefined,
        stop: () => undefined,
        reloadHistory: async () => undefined,
        reset: () => undefined,
        dismissNotice: () => undefined,
        ...overrides,
    }
}

const EDITING: SessionToolInvocation = {
    toolCallId: 'c3',
    toolName: 'Edit',
    kind: 'edit',
    status: 'in_progress',
    title: 'Edit Legend.tsx',
    detail: 'Pass the series name to the legend',
}

const INVOCATIONS = new Map<string, SessionToolInvocation>([
    ['c1', { toolCallId: 'c1', toolName: 'Bash', kind: 'execute', status: 'completed', title: 'pnpm test' }],
    ['c2', { toolCallId: 'c2', toolName: 'Read', kind: 'read', status: 'completed', title: 'Legend.tsx' }],
    ['c3', EDITING],
])

const TWO_GROUPS: SessionThreadItem[] = [
    { kind: 'user', id: 'u1', text: 'Fix the legend' },
    { kind: 'tool', id: 't1', toolCallId: 'c1' },
    { kind: 'tool', id: 't2', toolCallId: 'c2' },
    { kind: 'assistant', id: 'a1', text: 'The legend reads a stale prop.', complete: true },
    { kind: 'thought', id: 'th1', text: 'Change the **prop** `name`', complete: true },
    { kind: 'tool', id: 't3', toolCallId: 'c3' },
]

describe('SessionThread', () => {
    const capture = jest.fn()

    beforeEach(() => {
        capture.mockClear()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
    })

    afterEach(() => {
        jest.restoreAllMocks()
        setAnalyticsClient(null)
    })

    test.each(['user', 'assistant'] as const)('copies the full %s message with its formatting', async (role) => {
        const copy = jest.spyOn(Clipboard, 'setStringAsync').mockResolvedValue(true)
        const text = '  **A result**\n\n```sql\nSELECT 1\n```\n'
        const item: SessionThreadItem =
            role === 'user'
                ? { kind: 'user', id: 'message', text }
                : { kind: 'assistant', id: 'message', text, complete: true }
        render(<SessionThread session={session({ items: [item] })} onRetryHistory={jest.fn()} />)
        expect(screen.queryByText('Copy text')).toBeNull()

        await act(async () => fireEvent.press(screen.getByLabelText('Copy message text')))

        expect(copy).toHaveBeenCalledWith(text)
        expect(screen.getByLabelText('Message copied')).toBeTruthy()
        expect(screen.queryByText('Copied')).toBeNull()
        expect(capture).toHaveBeenCalledWith(
            'mobile_chat_message_copied',
            expect.objectContaining({ message_role: role, text_length: text.length })
        )
        expect(JSON.stringify(capture.mock.calls)).not.toContain('SELECT 1')
    })

    test.each(['sandbox', 'langgraph'] as const)('shows one set of actions per %s reply', async (runtime) => {
        const copy = jest.spyOn(Clipboard, 'setStringAsync').mockResolvedValue(true)
        const items: SessionThreadItem[] = [
            { kind: 'user', id: 'empty-user', text: '  ' },
            { kind: 'assistant', id: 'empty-assistant', text: '\n', complete: true },
            { kind: 'assistant', id: 'intro', text: 'I’ll check.', complete: true, traceId: 'trace-1' },
            {
                kind: 'assistant',
                id: 'chart',
                text: '[View chart](https://example.com/chart)',
                complete: true,
                traceId: 'trace-1',
            },
        ]
        const feedbackContext = { sessionId: 'task-1', runtime }
        const view = render(
            <SessionThread
                session={session({ items, phase: 'working' })}
                onRetryHistory={jest.fn()}
                feedbackContext={feedbackContext}
            />
        )
        expect(screen.queryByTestId('chat-copy-message')).toBeNull()
        expect(screen.queryByLabelText('Good answer')).toBeNull()

        view.rerender(
            <SessionThread
                session={session({
                    items: [
                        ...items,
                        { kind: 'assistant', id: 'reply', text: 'Final reply', complete: true, traceId: 'trace-1' },
                        ...(runtime === 'sandbox'
                            ? [{ kind: 'turn_end' as const, id: 'end', traceId: 'trace-1' }]
                            : []),
                    ],
                })}
                onRetryHistory={jest.fn()}
                feedbackContext={feedbackContext}
            />
        )
        await act(async () => fireEvent.press(screen.getByTestId('chat-copy-message')))
        expect(copy).toHaveBeenCalledWith('Final reply')
        expect(screen.getByLabelText('Good answer')).toBeTruthy()
        expect(screen.getByLabelText('Bad answer')).toBeTruthy()
    })

    test('keeps completed answers from rerendering while the next answer streams', () => {
        const renderMarkdown = jest.spyOn(markdown, 'ChatMarkdown')
        const history: SessionThreadItem[] = [
            { kind: 'user', id: 'first-prompt', text: 'Find the error' },
            { kind: 'assistant', id: 'first-answer', text: 'The request timed out.', complete: true },
            { kind: 'turn_end', id: 'first-end', traceId: 'trace-1', runId: 'run-1' },
            { kind: 'user', id: 'next-prompt', text: 'How can we retry?' },
        ]
        const thread = (text: string): ReactElement => (
            <SessionThread
                session={session({
                    items: [...history, { kind: 'assistant', id: 'next-answer', text, complete: false }],
                })}
                onRetryHistory={jest.fn()}
                feedbackContext={{ sessionId: 'task-1', runtime: 'sandbox' }}
            />
        )

        const { rerender } = render(thread('Retry'))
        expect(screen.getByLabelText('Good answer')).toBeTruthy()
        renderMarkdown.mockClear()

        rerender(thread('Retry the request.'))

        expect(renderMarkdown.mock.calls.map(([props]) => props.text)).toEqual(['Retry the request.'])
    })

    test.each(['rejected', 'false'] as const)(
        'prevents duplicate copies and allows retry after a %s write',
        async (failure) => {
            let resolveCopy!: (copied: boolean) => void
            let rejectCopy!: (error: Error) => void
            const copy = jest.spyOn(Clipboard, 'setStringAsync').mockImplementationOnce(
                () =>
                    new Promise<boolean>((resolve, reject) => {
                        resolveCopy = resolve
                        rejectCopy = reject
                    })
            )
            render(
                <SessionThread
                    session={session({ items: [{ kind: 'user', id: 'message', text: 'Copy this message' }] })}
                    onRetryHistory={jest.fn()}
                />
            )

            fireEvent.press(screen.getByTestId('chat-copy-message'))
            fireEvent.press(screen.getByTestId('chat-copy-message'))
            expect(copy).toHaveBeenCalledTimes(1)
            expect(screen.getByTestId('chat-copy-message')).toBeDisabled()
            expect(screen.queryByLabelText('Message copied')).toBeNull()
            await act(async () => {
                if (failure === 'rejected') rejectCopy(new Error('Clipboard unavailable'))
                else resolveCopy(false)
            })
            expect(screen.getByText("Couldn't copy the message. Try again.")).toBeTruthy()
            expect(screen.getByTestId('chat-copy-message')).toBeEnabled()
            expect(capture).toHaveBeenCalledWith('mobile_chat_message_copy_failed', expect.anything())
            expect(capture.mock.calls.some(([event]) => event === 'mobile_chat_message_copied')).toBe(false)

            copy.mockResolvedValueOnce(true)
            await act(async () => fireEvent.press(screen.getByTestId('chat-copy-message')))
            expect(screen.getByLabelText('Message copied')).toBeTruthy()
            expect(screen.queryByText("Couldn't copy the message. Try again.")).toBeNull()
        }
    )

    test('keeps received messages visible without a reconnecting indicator', () => {
        render(
            <SessionThread
                session={session({ items: TWO_GROUPS.slice(0, 1), phase: 'reconnecting' })}
                onRetryHistory={jest.fn()}
            />
        )
        expect(screen.getByText('Fix the legend')).toBeTruthy()
        expect(screen.queryByText('Reconnecting…')).toBeNull()
        expect(screen.UNSAFE_queryByType(ActivityIndicator)).toBeNull()
    })

    test.each([
        ['above newer messages', 200],
        ['at the bottom', 1300],
    ])('preserves the viewport when toggling a notice %s', (_name, offset) => {
        const scrollToEnd = jest.spyOn(ScrollView.prototype, 'scrollToEnd')
        const items: SessionThreadItem[] = [
            { kind: 'notice', id: 'n1', text: 'The background review finished.', tone: 'completed' },
            ...TWO_GROUPS,
        ]
        render(<SessionThread session={session({ items })} onRetryHistory={jest.fn()} />)
        const thread = screen.getByTestId('session-thread')
        fireEvent(screen.getByTestId('session-notice-measure-n1', { includeHiddenElements: true }), 'textLayout', {
            nativeEvent: { lines: [{ text: 'First line' }, { text: 'Second line' }, { text: 'Third line' }] },
        })
        fireEvent(thread, 'contentSizeChange', 400, 1800)
        expect(scrollToEnd).toHaveBeenLastCalledWith({ animated: false })
        fireEvent(thread, 'contentSizeChange', 400, 1850)
        expect(scrollToEnd).toHaveBeenLastCalledWith({ animated: true })
        scrollToEnd.mockClear()

        fireEvent(thread, 'scrollBeginDrag')
        fireEvent(thread, 'scrollEndDrag', {
            nativeEvent: {
                contentOffset: { y: offset },
                contentSize: { height: 1800 },
                layoutMeasurement: { height: 500 },
            },
        })
        fireEvent.press(screen.getByText('Show more'))
        fireEvent(thread, 'contentSizeChange', 400, 2000)
        fireEvent.press(screen.getByText('Show less'))
        fireEvent(thread, 'contentSizeChange', 400, 1800)
        fireEvent(thread, 'contentSizeChange', 400, 1850)
        expect(scrollToEnd).not.toHaveBeenCalled()

        fireEvent(thread, 'scrollBeginDrag')
        fireEvent(thread, 'momentumScrollEnd', {
            nativeEvent: {
                contentOffset: { y: 1350 },
                contentSize: { height: 1850 },
                layoutMeasurement: { height: 500 },
            },
        })
        fireEvent(thread, 'contentSizeChange', 400, 1900)
        expect(scrollToEnd).toHaveBeenCalledTimes(1)
        expect(scrollToEnd).toHaveBeenCalledWith({ animated: true })
    })

    test('shows a retry state when the history fails to load', () => {
        const onRetryHistory = jest.fn()
        render(
            <SessionThread
                session={session({
                    history: { status: 'error', error: { kind: 'network', message: 'No connection' } },
                })}
                onRetryHistory={onRetryHistory}
            />
        )
        expect(screen.getByTestId('session-history-error')).toHaveTextContent(/No connection/)
        fireEvent.press(screen.getByText('Try again'))
        expect(onRetryHistory).toHaveBeenCalledTimes(1)
        expect(screen.queryByTestId('session-thread')).toBeNull()
    })

    test('keeps running and settled groups closed, and opens one on press', () => {
        render(
            <SessionThread
                session={session({ items: TWO_GROUPS, invocations: INVOCATIONS, phase: 'working', stage: 'Editing' })}
                onRetryHistory={jest.fn()}
            />
        )
        expect(screen.getByLabelText('Ran 1 command, read a file')).toBeTruthy()
        expect(screen.queryByTestId('session-tool-c1')).toBeNull()
        expect(screen.queryByTestId('session-tool-c3')).toBeNull()
        expect(screen.getByTestId('chat-progress')).toHaveTextContent('Editing')

        fireEvent.press(screen.getByLabelText('Ran 1 command, read a file'))
        expect(screen.getByTestId('session-tool-c1')).toBeTruthy()
        fireEvent.press(screen.getByLabelText('Edit Legend.tsx'))
        expect(screen.getByTestId('session-tool-c3')).toHaveTextContent(/Pass the series name to the legend/)
        expect(screen.getByText('prop')).toBeTruthy()
        expect(screen.getByText('name')).toBeTruthy()
        expect(screen.queryByText(/\*\*|`/)).toBeNull()
    })

    test('keeps the PR visible while working and once the last group settles', () => {
        const props = {
            items: TWO_GROUPS,
            phase: 'working' as const,
            pullRequest: { url: 'https://github.com/example/repo/pull/7', number: 7, state: 'unknown' as const },
        }
        const { rerender } = render(
            <SessionThread session={session({ ...props, invocations: INVOCATIONS })} onRetryHistory={jest.fn()} />
        )
        expect(screen.getByLabelText('Edit Legend.tsx')).toBeTruthy()
        expect(screen.getByTestId('pr-ready-card')).toBeTruthy()
        expect(screen.getByTestId('pull-request-state')).toHaveTextContent('Status unavailable')

        const settled = new Map(INVOCATIONS)
        settled.set('c3', { ...EDITING, status: 'completed' })
        rerender(
            <SessionThread
                session={session({
                    ...props,
                    invocations: settled,
                    phase: 'idle',
                    runStatus: 'completed',
                    pullRequest: { url: 'https://github.com/example/repo/pull/7', number: 7, state: 'open' },
                })}
                onRetryHistory={jest.fn()}
            />
        )
        expect(screen.queryByTestId('session-tool-c3')).toBeNull()
        expect(screen.getByLabelText('Edited a file')).toBeTruthy()
        expect(screen.getByTestId('pr-ready-card')).toBeTruthy()
        expect(screen.queryByTestId('chat-progress')).toBeNull()
    })

    test.each<[string, SessionThreadItem[]]>([
        ['from the run error alone', []],
        [
            'once when an error item already carries it',
            [{ kind: 'error', id: 'e1', message: 'Sandbox timed out', variant: 'crash' }],
        ],
    ])('shows a failed run %s', (_name, items) => {
        render(
            <SessionThread
                session={session({ items, runStatus: 'failed', runError: 'Sandbox timed out' })}
                onRetryHistory={jest.fn()}
            />
        )
        expect(screen.getAllByTestId('chat-error')).toHaveLength(1)
        expect(screen.getByText(/Sandbox timed out/)).toBeTruthy()
    })
})
