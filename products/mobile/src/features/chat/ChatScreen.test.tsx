import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { Platform, TextInput } from 'react-native'
import { ChatScreen } from './ChatScreen'
import { queueActions, queueReducer } from './messageQueue'
import { useSession } from './session/useSession'
import { useChatDraft } from './useChatDraft'

jest.mock('expo-notifications', () => ({}))
jest.mock('react-native-gesture-handler', () => ({
    ...jest.requireActual('react-native-gesture-handler'),
    GestureHandlerRootView: require('react-native').View,
}))
jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock('@/features/status/usePostHogStatus', () => ({
    usePostHogStatus: () => ({
        pageUrl: 'https://www.posthogstatus.com/eu',
        summary: 'Elevated latency',
        aiIncident: {
            status: 'monitoring',
            color: 'yellow',
            title: 'Elevated latency',
            url: 'https://www.posthogstatus.com/incidents/example',
        },
    }),
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 1 }) }))
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))
jest.mock('@/features/chats/hooks', () => ({ useArchiveChat: () => ({ archive: jest.fn() }) }))
jest.mock('../inbox/hooks', () => ({ useInboxItems: () => ({ data: [] }) }))
jest.mock('../handoff/useRunOptions', () => ({
    useRunDefaults: () => undefined,
    useModelCatalogue: () => ({ catalogue: [], loading: false, unavailable: false }),
}))
jest.mock('./ChatAccessGate', () => ({ ChatAccessGate: ({ children }: { children: React.ReactNode }) => children }))
jest.mock('./ChatOptionsSheet', () => ({ ChatOptionsSheet: () => null }))
jest.mock('./session/SessionThread', () => ({ SessionThread: () => null }))
jest.mock('./session/useSession', () => ({ useSession: jest.fn() }))
jest.mock('./useChatDraft', () => ({ useChatDraft: jest.fn() }))

beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
})
afterEach(() => {
    act(() => jest.runOnlyPendingTimers())
    jest.useRealTimers()
})

function mockReadyChat(): { session: ReturnType<typeof useSession>; draft: ReturnType<typeof useChatDraft> } {
    const session: ReturnType<typeof useSession> = {
        taskId: 'task-1',
        runId: 'run-1',
        title: 'Example chat',
        runStatus: 'completed',
        items: [],
        invocations: new Map(),
        phase: 'idle',
        history: { status: 'idle', error: null },
        isSending: false,
        isStopping: false,
        canSteer: false,
        start: jest.fn(async () => true),
        send: jest.fn(async () => true),
        answer: jest.fn(),
        stop: jest.fn(),
        reloadHistory: jest.fn(),
        reset: jest.fn(),
        dismissNotice: jest.fn(),
    }
    const draft: ReturnType<typeof useChatDraft> = {
        draft: { text: 'First message', reportIds: [] },
        ready: true,
        queue: { rows: [], hold: null },
        queuePending: false,
        draftError: undefined,
        draftSaving: false,
        retrySave: jest.fn(async () => undefined),
        queueError: undefined,
        dismissQueueError: jest.fn(),
        updateQueue: jest.fn(async () => true),
        change: jest.fn(),
        beginSend: jest.fn(async () => async () => undefined),
    }
    jest.mocked(useSession).mockImplementation(() => session)
    jest.mocked(useChatDraft).mockImplementation(() => draft)
    return { session, draft }
}

test.each([null, 'task-1'])('shows the regional AI incident for chat %s', (taskId) => {
    const { session } = mockReadyChat()
    session.taskId = taskId
    render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
    expect(screen.getByLabelText('PostHog AI incident (monitoring) · Elevated latency')).toBeTruthy()
})

describe('chat send preparation', () => {
    test('focuses the composer only when the route is ready', () => {
        mockReadyChat()
        const focus = jest.mocked(TextInput.prototype.focus)
        const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        expect(focus).not.toHaveBeenCalled()

        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} autoFocus onBack={jest.fn()} />)
        expect(focus).toHaveBeenCalledTimes(1)
        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} autoFocus onBack={jest.fn()} />)
        expect(focus).toHaveBeenCalledTimes(1)
    })

    test('keeps an unsaved draft notice visible and disables retry while saving', () => {
        const { session, draft } = mockReadyChat()
        session.notice = 'Connection interrupted. Reconnect to continue.'
        session.reconnect = jest.fn()
        draft.draftError = 'Draft not saved. Remove a queued message before saving more.'
        const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        expect(screen.getByDisplayValue('First message')).toBeTruthy()
        expect(screen.getByText(draft.draftError)).toBeTruthy()
        expect(screen.queryByTestId('session-reconnect')).toBeNull()
        fireEvent.press(screen.getByTestId('chat-draft-retry'))
        expect(draft.retrySave).toHaveBeenCalledTimes(1)
        draft.draftSaving = true
        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        expect(screen.getByText('Saving…')).toBeTruthy()
        fireEvent.press(screen.getByTestId('chat-draft-retry'))
        expect(draft.retrySave).toHaveBeenCalledTimes(1)
        draft.draftSaving = false
        draft.draftError = undefined
        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        expect(screen.queryByTestId('chat-draft-retry')).toBeNull()
        expect(screen.getByText(session.notice)).toBeTruthy()
        fireEvent.press(screen.getByTestId('session-reconnect'))
        expect(session.reconnect).toHaveBeenCalledTimes(1)
    })
    test.each(['new', 'close', 'unmount'])('a prepared message does not send after %s', async (transition) => {
        let finishStorage!: (settle: (sent: boolean) => Promise<void>) => void
        const beginSend = jest.fn(
            () =>
                new Promise<(sent: boolean) => Promise<void>>((resolve) => {
                    finishStorage = resolve
                })
        )
        const send = jest.fn(async () => true)
        const reset = jest.fn()
        const settle = jest.fn(async () => undefined)
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: 'Continue the old chat', reportIds: [] },
            ready: true,
            queue: { rows: [], hold: null },
            queuePending: false,
            draftError: undefined,
            draftSaving: false,
            retrySave: jest.fn(async () => undefined),
            queueError: undefined,
            dismissQueueError: jest.fn(),
            updateQueue: jest.fn(async () => true),
            change: jest.fn(),
            beginSend,
        })
        jest.mocked(useSession).mockReturnValue({
            taskId: 'task-1',
            runId: 'run-1',
            title: 'Old chat',
            runStatus: 'completed',
            items: [],
            invocations: new Map(),
            phase: 'idle',
            history: { status: 'idle', error: null },
            isSending: false,
            isStopping: false,
            canSteer: false,
            start: send,
            send,
            answer: jest.fn(),
            stop: jest.fn(),
            reloadHistory: jest.fn(),
            reset,
            dismissNotice: jest.fn(),
        })
        const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        fireEvent.press(screen.getByTestId('chat-send'))
        expect(beginSend).toHaveBeenCalled()
        if (transition === 'unmount') {
            view.unmount()
        } else {
            fireEvent.press(screen.getByTestId(transition === 'new' ? 'chat-new' : 'chat-back'))
        }
        await act(async () => {
            finishStorage(settle)
        })
        expect(send).not.toHaveBeenCalled()
        expect(settle).toHaveBeenCalledWith(false)
        if (transition === 'new') expect(reset).toHaveBeenCalledTimes(1)
    })
    it('cancels a queued delivery when Stop is pressed before the recovery write finishes', async () => {
        let finishStorage!: (saved: boolean) => void
        const updateQueue = jest
            .fn<Promise<boolean>, Parameters<ReturnType<typeof useChatDraft>['updateQueue']>>()
            .mockImplementationOnce(
                () =>
                    new Promise<boolean>((resolve) => {
                        finishStorage = resolve
                    })
            )
            .mockResolvedValue(true)
        const send = jest.fn(async () => true)
        const stop = jest.fn()
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
            queue: { rows: [{ id: 'queued-1', text: 'Wait for me', attachments: [] }], hold: null },
            queuePending: false,
            draftError: undefined,
            draftSaving: false,
            retrySave: jest.fn(async () => undefined),
            queueError: undefined,
            dismissQueueError: jest.fn(),
            updateQueue,
            change: jest.fn(),
            beginSend: jest.fn(),
        })
        jest.mocked(useSession).mockReturnValue({
            taskId: 'task-1',
            runId: 'run-1',
            title: 'Chat',
            runStatus: 'in_progress',
            items: [],
            invocations: new Map(),
            phase: 'working',
            history: { status: 'idle', error: null },
            isSending: false,
            isStopping: false,
            canSteer: true,
            start: send,
            send,
            answer: jest.fn(),
            stop,
            reloadHistory: jest.fn(),
            reset: jest.fn(),
            dismissNotice: jest.fn(),
        })
        render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        fireEvent.press(screen.getByTestId('chat-queue-send-now'))
        expect(send).not.toHaveBeenCalled()
        fireEvent.press(screen.getByTestId('chat-stop'))
        expect(stop).toHaveBeenCalledTimes(1)
        await act(async () => {
            finishStorage(true)
        })
        expect(send).not.toHaveBeenCalled()
    })
    it.each(['stop', 'new', 'close', 'unmount'])(
        'handles queue acknowledgment after %s interrupts delivery',
        async (transition) => {
            const { session, draft } = mockReadyChat()
            session.phase = 'working'
            session.canSteer = true
            draft.queue = { rows: [{ id: 'queued-1', text: 'Follow up', attachments: [] }], hold: 'unconfirmed' }
            jest.mocked(draft.updateQueue).mockImplementation(async (action) => {
                draft.queue = queueReducer(draft.queue, action)
                return true
            })
            let finish!: (sent: boolean) => void
            jest.mocked(session.send).mockImplementationOnce(
                () =>
                    new Promise<boolean>((resolve) => {
                        finish = resolve
                    })
            )
            const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
            await act(async () => {
                fireEvent.press(screen.getByTestId('chat-queue-send-now'))
            })
            expect(session.send).toHaveBeenCalledTimes(1)
            draft.queue = queueReducer(draft.queue, queueActions.enqueue('Later question'))
            if (transition === 'unmount') view.unmount()
            else
                fireEvent.press(
                    screen.getByTestId(
                        transition === 'new' ? 'chat-new' : transition === 'close' ? 'chat-back' : 'chat-stop'
                    )
                )
            await act(async () => {
                finish(true)
            })
            if (transition === 'stop') {
                session.phase = 'idle'
                view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
                expect(screen.queryByText('Follow up')).toBeNull()
                expect(screen.getByText('Later question')).toBeTruthy()
                expect(draft.queue.hold).toBe('cancelled')
                expect(session.send).toHaveBeenCalledTimes(1)
            } else {
                expect(draft.queue.rows.map((row) => row.text)).toEqual(['Follow up', 'Later question'])
            }
        }
    )

    it.each(['loading', 'error'] as const)(
        'waits for history before sending a recovered queue, history=%s',
        async (status) => {
            const { session, draft } = mockReadyChat()
            session.history = { status, error: null }
            draft.queue = {
                rows: [{ id: 'queued-1', text: 'Recovered question', attachments: [] }],
                hold: 'unconfirmed',
            }
            const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
            expect(screen.getByTestId('chat-queue-send-now').props.accessibilityState.disabled).toBe(true)
            fireEvent.press(screen.getByTestId('chat-queue-send-now'))
            expect(session.send).not.toHaveBeenCalled()
            session.history = { status: 'idle', error: null }
            view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
            await act(async () => {
                fireEvent.press(screen.getByTestId('chat-queue-send-now'))
            })
            expect(session.send).toHaveBeenCalledTimes(1)
        }
    )

    it('allows another direct send after Stop interrupts a pending direct reply', async () => {
        const { session, draft } = mockReadyChat()
        let finishSend!: (sent: boolean) => void
        let started!: () => void
        const sending = new Promise<void>((resolve) => {
            started = resolve
        })
        jest.mocked(session.send).mockImplementationOnce(() => {
            started()
            return new Promise<boolean>((resolve) => {
                finishSend = resolve
            })
        })
        const view = render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        await act(async () => {
            fireEvent.press(screen.getByTestId('chat-send'))
            await sending
        })
        session.phase = 'working'
        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        fireEvent.press(screen.getByTestId('chat-stop'))
        await act(async () => {
            finishSend(false)
        })
        session.phase = 'idle'
        view.rerender(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        await act(async () => {
            fireEvent.press(screen.getByTestId('chat-send'))
        })
        expect(draft.beginSend).toHaveBeenCalledTimes(2)
        expect(draft.updateQueue).toHaveBeenCalledWith({ type: 'hold', reason: 'cancelled' })
        expect(draft.updateQueue).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'enqueue' }), true)
    })

    it('does not start a new conversation while a taskless queue still holds messages', () => {
        const { session, draft } = mockReadyChat()
        session.taskId = null
        draft.draft = { text: '', reportIds: [] }
        draft.queue = { rows: [{ id: 'queued-1', text: 'Keep this question', attachments: [] }], hold: 'cancelled' }
        render(<ChatScreen source={{ entry: 'compose', origin: null }} onBack={jest.fn()} />)
        expect(screen.queryByTestId('chat-new')).toBeNull()
        expect(session.reset).not.toHaveBeenCalled()
        expect(session.send).not.toHaveBeenCalled()
        expect(screen.getByText('Keep this question')).toBeTruthy()
    })
})

const originalPlatform = Platform.OS
beforeAll(() => {
    Platform.OS = 'android'
})
afterAll(() => {
    Platform.OS = originalPlatform
})
