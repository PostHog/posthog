import { fireEvent, render, screen } from '@testing-library/react-native'

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
