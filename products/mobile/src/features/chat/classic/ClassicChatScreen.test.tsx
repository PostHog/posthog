import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'

import { useChatDraft } from '../useChatDraft'
import { ClassicChatScreen } from './ClassicChatScreen'
import { useClassicChat } from './useClassicChat'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => jest.requireActual('react-native-reanimated/mock'))
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))
jest.mock('../ChatAccessGate', () => ({ ChatAccessGate: ({ children }: { children: React.ReactNode }) => children }))
jest.mock('../ChatEmptyState', () => ({ ChatEmptyState: () => null }))
jest.mock('../ChatHeader', () => {
    const { Button, View } = require('react-native')
    return {
        CHAT_HEADER_HEIGHT: 52,
        ChatHeader: ({ onBack, onNewChat }: { onBack: () => void; onNewChat: () => void }) => (
            <View>
                <Button title="Back" onPress={onBack} />
                <Button title="New chat" onPress={onNewChat} />
            </View>
        ),
    }
})
jest.mock('../session/SessionThread', () => ({ SessionThread: () => null }))
jest.mock('../chatSheetEvents', () => ({
    useChatSheetEvents: () => ({ countSent: jest.fn(), countNewChat: jest.fn() }),
}))
jest.mock('../useChatDraft', () => ({ useChatDraft: jest.fn() }))
jest.mock('./useClassicChat', () => ({ useClassicChat: jest.fn() }))

describe('classic chat draft recovery', () => {
    test('keeps the unsaved text visible and guards retry until storage settles', async () => {
        let finish!: () => void
        const retrySave = jest.fn(
            () =>
                new Promise<void>((resolve) => {
                    finish = resolve
                })
        )
        const draft = {
            draft: { text: 'Saved question', reportIds: [] },
            ready: true,
            draftError: 'Draft not saved. Try saving again.',
            retrySave,
        } as unknown as ReturnType<typeof useChatDraft>
        jest.mocked(useChatDraft).mockReturnValue(draft)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            historyError: null,
            working: false,
            error: 'Reply failed. Try again.',
            state: { messages: [], title: null, approval: null, progress: null, error: null },
        } as unknown as ReturnType<typeof useClassicChat>)
        const element = (
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        const view = render(element)
        expect(screen.getByDisplayValue('Saved question')).toBeTruthy()
        expect(screen.getByText(draft.draftError as string)).toBeTruthy()
        expect(screen.getByText('Reply failed. Try again.')).toBeTruthy()
        fireEvent.press(screen.getByLabelText('Retry saving draft'))
        fireEvent.press(screen.getByLabelText('Retry saving draft'))
        expect(retrySave).toHaveBeenCalledTimes(1)
        await act(async () => {
            finish()
        })
        draft.draftError = undefined
        view.rerender(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        expect(screen.queryByLabelText('Retry saving draft')).toBeNull()
        expect(screen.getByDisplayValue('Saved question')).toBeTruthy()
    })
    test.each(['Back', 'New chat', 'unmount'])('restores a prepared draft after %s', async (transition) => {
        let finish!: (settle: (sent: boolean) => Promise<void>) => void
        const settle = jest.fn(async () => undefined)
        const send = jest.fn()
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: 'Unsent question', reportIds: [] },
            ready: true,
            beginSend: () =>
                new Promise((resolve) => {
                    finish = resolve
                }),
        } as unknown as ReturnType<typeof useChatDraft>)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            working: false,
            state: { messages: [], approval: null },
            send,
            reset: jest.fn(),
        } as unknown as ReturnType<typeof useClassicChat>)
        const view = render(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        fireEvent.press(screen.getByTestId('chat-send'))
        if (transition === 'unmount') view.unmount()
        else fireEvent.press(screen.getByText(transition))
        await act(async () => {
            finish(settle)
        })
        expect(send).not.toHaveBeenCalled()
        expect(settle).toHaveBeenCalledWith(false)
    })
    test('settles an accepted draft while the reply is still streaming', async () => {
        const settle = jest.fn(async () => undefined)
        let finish!: (accepted: boolean) => void
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: 'A question', reportIds: [] },
            ready: true,
            beginSend: async () => settle,
        } as unknown as ReturnType<typeof useChatDraft>)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            working: false,
            historyError: null,
            stopping: false,
            error: null,
            state: { messages: [], approval: null, title: null, progress: null, error: null },
            answer: jest.fn(),
            stop: jest.fn(),
            reload: jest.fn(),
            reset: jest.fn(),
            dismissError: jest.fn(),
            send: async (_text, onAccepted) => {
                await onAccepted?.()
                return new Promise((resolve) => {
                    finish = resolve
                })
            },
        })
        render(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        fireEvent.press(screen.getByTestId('chat-send'))
        await waitFor(() => expect(settle).toHaveBeenCalledWith(true))
        await act(async () => {
            finish(true)
        })
        expect(settle).toHaveBeenCalledTimes(1)
    })
})
