import { act, fireEvent, render, screen } from '@testing-library/react-native'
import * as Clipboard from 'expo-clipboard'
import type { ReactElement } from 'react'

import { taskWebUrl } from '@/model/adapters/chats'
import { OverlayHost } from '@/ui/OverlayPortal'

import { ChatHeader } from './ChatHeader'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

afterEach(() => jest.restoreAllMocks())

describe('ChatHeader', () => {
    test('copies the current chat from its menu and follows chat and project changes', async () => {
        const copy = jest.spyOn(Clipboard, 'setStringAsync').mockResolvedValue(true)
        const scope = { host: 'https://us.posthog.com/', projectId: 7 }
        const onBack = jest.fn()
        const onNewChat = jest.fn()
        const header = (url: string | undefined): ReactElement => (
            <ChatHeader webUrl={url} onBack={onBack} onNewChat={onNewChat} />
        )
        const view = render(header(taskWebUrl(scope, null)), { wrapper: OverlayHost })
        expect(screen.getByTestId('chat-more')).toBeDisabled()
        expect(screen.queryByTestId('chat-copy-link')).toBeNull()

        view.rerender(header(taskWebUrl(scope, 'first-task')))
        fireEvent.press(screen.getByTestId('chat-more'))
        expect(screen.getByText('Copy link to chat')).toBeTruthy()
        expect(screen.getByTestId('chat-archive')).toBeDisabled()
        await act(async () => fireEvent.press(screen.getByTestId('chat-copy-link')))
        expect(copy).toHaveBeenLastCalledWith('https://us.posthog.com/project/7/ai?task=first-task')
        expect(screen.getByText('Chat link copied')).toBeTruthy()
        expect(screen.getByTestId('chat-more').props.accessibilityState.expanded).toBe(false)

        view.rerender(header(taskWebUrl({ host: 'https://eu.posthog.com', projectId: 9 }, 'next-task')))
        fireEvent.press(screen.getByTestId('chat-more'))
        await act(async () => fireEvent.press(screen.getByTestId('chat-copy-link')))
        expect(copy).toHaveBeenLastCalledWith('https://eu.posthog.com/project/9/ai?task=next-task')
        fireEvent.press(screen.getByTestId('chat-new'))
        expect(onNewChat).toHaveBeenCalledTimes(1)
        fireEvent.press(screen.getByTestId('chat-back'))
        expect(onBack).toHaveBeenCalledTimes(1)
    })

    test.each(['rejected', 'false'] as const)(
        'prevents duplicate copies, reports a %s write and allows retry',
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
                <ChatHeader
                    webUrl="https://us.posthog.com/project/7/ai?task=task-1"
                    onBack={jest.fn()}
                    onNewChat={jest.fn()}
                />,
                { wrapper: OverlayHost }
            )
            fireEvent.press(screen.getByTestId('chat-more'))
            fireEvent.press(screen.getByTestId('chat-copy-link'))
            fireEvent.press(screen.getByTestId('chat-copy-link'))
            expect(copy).toHaveBeenCalledTimes(1)
            expect(screen.getByTestId('chat-copy-link')).toBeDisabled()
            expect(screen.queryByText('Chat link copied')).toBeNull()
            await act(async () => {
                if (failure === 'rejected') {
                    rejectCopy(new Error('Clipboard unavailable'))
                } else {
                    resolveCopy(false)
                }
            })
            expect(screen.getByText("Couldn't copy the link. Try again.")).toBeTruthy()
            expect(screen.getByTestId('chat-more').props.accessibilityState.expanded).toBe(true)
            expect(screen.getByTestId('chat-copy-link')).toBeEnabled()

            copy.mockResolvedValueOnce(true)
            await act(async () => fireEvent.press(screen.getByTestId('chat-copy-link')))
            expect(copy).toHaveBeenCalledTimes(2)
            expect(screen.getByText('Chat link copied')).toBeTruthy()
        }
    )

    test('guards archive against double taps and allows retry after failure', async () => {
        let rejectArchive!: (error: Error) => void
        const onArchive = jest.fn(
            () =>
                new Promise<void>((_, reject) => {
                    rejectArchive = reject
                })
        )
        render(
            <ChatHeader
                webUrl="https://us.posthog.com/project/7/ai?task=task-1"
                onBack={jest.fn()}
                onNewChat={jest.fn()}
                onArchive={onArchive}
            />,
            { wrapper: OverlayHost }
        )
        fireEvent.press(screen.getByTestId('chat-more'))
        fireEvent.press(screen.getByTestId('chat-archive'))
        fireEvent.press(screen.getByTestId('chat-archive'))
        expect(onArchive).toHaveBeenCalledTimes(1)
        expect(screen.getByTestId('chat-archive')).toBeDisabled()
        expect(screen.getByTestId('chat-copy-link')).toBeDisabled()
        await act(async () => rejectArchive(new Error('offline')))
        expect(screen.getByText("Couldn't archive this chat. Try again.")).toBeTruthy()
        expect(screen.getByTestId('chat-archive')).toBeEnabled()
        expect(screen.getByTestId('chat-more').props.accessibilityState.expanded).toBe(true)

        onArchive.mockResolvedValueOnce(undefined)
        await act(async () => fireEvent.press(screen.getByTestId('chat-archive')))
        expect(onArchive).toHaveBeenCalledTimes(2)
        expect(screen.getByTestId('chat-more').props.accessibilityState.expanded).toBe(false)
    })
})
