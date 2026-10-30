import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { ChatScreen } from './ChatScreen'
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

describe('chat send preparation', () => {
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
})
