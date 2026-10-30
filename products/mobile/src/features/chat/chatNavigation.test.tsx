import * as Notifications from 'expo-notifications'
import { router } from 'expo-router'
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { AppState, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { setViewedNotificationTask } from '@/features/notifications/foregroundNotifications'
import { findTask } from '@/features/notifications/taskLookup'
import { useDefaultPageStore } from '@/features/settings/defaultPageStore'

import RootLayout from '../../../app/_layout'
import ChatRoute from '../../../app/chat'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-keyboard-controller', () => ({ KeyboardProvider: require('react-native').View }))
jest.mock('@/auth/BootSplash', () => ({ BootSplash: require('react-native').View }))
jest.mock('expo-splash-screen', () => ({
    preventAutoHideAsync: jest.fn(async () => undefined),
    setOptions: jest.fn(),
    hideAsync: jest.fn(async () => undefined),
}))
jest.mock('@/demo/demoMode', () => ({
    useDemoHydrated: () => true,
    useDataMode: () => 'live',
    useDemoMode: Object.assign((selector: (state: { enabled: boolean }) => unknown) => selector({ enabled: false }), {
        getState: () => ({ enabled: false }),
    }),
}))
jest.mock('@/features/chat/draftPersistence', () => ({}))
jest.mock('@/features/hedgehog/useHedgehogWidgetSync', () => ({ useHedgehogWidgetSync: jest.fn() }))
jest.mock('@/features/notifications/pushRegistration', () => ({ configureNotifications: jest.fn() }))
jest.mock('@/features/notifications/usePushRegistration', () => ({ usePushRegistration: jest.fn() }))
jest.mock('expo-notifications', () => ({
    getLastNotificationResponse: jest.fn(() => null),
    clearLastNotificationResponse: jest.fn(),
    addNotificationResponseReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
}))
jest.mock('@/features/notifications/pushSupport', () => ({ notificationsSupported: () => true }))
jest.mock('@/features/notifications/taskLookup', () => ({ findTask: jest.fn() }))
jest.mock('@/lib/posthogClient', () => ({ initAnalytics: jest.fn() }))
jest.mock('@/features/chat/ChatScreen', () => {
    const { useEffect, useState } = jest.requireActual<typeof import('react')>('react')
    const { Button, Text, TextInput, View } = jest.requireActual<typeof import('react-native')>('react-native')
    const { setViewedNotificationTask } = jest.requireActual<
        typeof import('@/features/notifications/foregroundNotifications')
    >('@/features/notifications/foregroundNotifications')
    return {
        ChatScreen: ({ initialTaskId, onBack }: { initialTaskId?: string; onBack: () => void }): ReactElement => {
            const [taskId, setTaskId] = useState(initialTaskId)
            const [draft, setDraft] = useState('')
            useEffect(() => {
                setViewedNotificationTask(
                    taskId ? { accountKey: 'https://app.example.com|chat-navigation-user', projectId: 2, taskId } : null
                )
                return () => setViewedNotificationTask(null)
            }, [taskId])
            return (
                <View testID="chat-screen">
                    <Text testID="loaded-task">{taskId ?? 'new'}</Text>
                    <TextInput testID="draft" value={draft} onChangeText={setDraft} />
                    <Button title="Back" testID="chat-back" onPress={onBack} />
                    <Button title="Start task" testID="start-task" onPress={() => setTaskId('task-a')} />
                    <Button title="New chat" testID="new-chat" onPress={() => setTaskId(undefined)} />
                </View>
            )
        },
    }
})

function Inbox(): ReactElement {
    return <View testID="inbox-screen" />
}

describe('chat navigation', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        setViewedNotificationTask(null)
        useDefaultPageStore.setState({ page: null })
        AppState.currentState = 'active'
        jest.mocked(findTask).mockResolvedValue({ found: true, reportId: null })
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://app.example.com',
            user: { uuid: 'chat-navigation-user' } as NonNullable<ReturnType<typeof useAuthStore.getState>['user']>,
            projectId: 2,
            restore: async () => undefined,
        })
    })

    test('reuses one chat screen, preserves the same chat draft and loads a different conversation', () => {
        const app = renderRouter({ _layout: RootLayout, inbox: Inbox, chat: ChatRoute }, { initialUrl: '/inbox' })
        act(() => router.push('/chat?taskId=task-a&entry=chats_list'))
        fireEvent.changeText(screen.getByTestId('draft'), 'Unsent message')

        act(() => router.push('/chat?taskId=task-a&from=push'))
        expect(screen.getAllByTestId('chat-screen')).toHaveLength(1)
        expect(screen.getByTestId('draft').props.value).toBe('Unsent message')

        act(() => router.push('/chat?taskId=task-b&from=push'))
        expect(screen.getAllByTestId('chat-screen')).toHaveLength(1)
        expect(screen.getByTestId('loaded-task').props.children).toBe('task-b')
        expect(screen.getByTestId('draft').props.value).toBe('')

        fireEvent.press(screen.getByTestId('chat-back'))
        expect(app.getPathname()).toBe('/inbox')
        expect(screen.queryByTestId('chat-screen')).toBeNull()
    })

    test.each(['/chat', '/chat?taskId=task-a'])('uses the default page for a direct link to %s', (initialUrl) => {
        useDefaultPageStore.setState({ page: 'views' })
        const app = renderRouter({ _layout: RootLayout, inbox: Inbox, views: Inbox, chat: ChatRoute }, { initialUrl })
        fireEvent.press(screen.getByTestId('chat-back'))
        expect(app.getPathname()).toBe('/views')
    })

    test.each([
        { name: 'same chat', initialTaskId: 'task-a', action: null, preserveDraft: true },
        { name: 'different chat', initialTaskId: 'task-b', action: null, preserveDraft: false },
        { name: 'chat started in the composer', initialTaskId: null, action: 'start-task', preserveDraft: true },
        { name: 'New chat after leaving this task', initialTaskId: 'task-a', action: 'new-chat', preserveDraft: false },
    ])('handles background notification taps for $name', async ({ name, initialTaskId, action, preserveDraft }) => {
        const app = renderRouter({ _layout: RootLayout, inbox: Inbox, chat: ChatRoute }, { initialUrl: '/inbox' })
        act(() => router.push(initialTaskId ? `/chat?taskId=${initialTaskId}` : '/chat'))
        if (action) {
            fireEvent.press(screen.getByTestId(action))
        }
        fireEvent.changeText(screen.getByTestId('draft'), 'Keep this draft')
        AppState.currentState = 'background'

        const listener = jest.mocked(Notifications.addNotificationResponseReceivedListener).mock.calls.at(-1)?.[0]
        if (!listener) {
            throw new Error('Notification listener was not registered')
        }
        const response: Notifications.NotificationResponse = {
            actionIdentifier: 'default',
            notification: {
                date: Date.now(),
                request: {
                    identifier: `background-${name}`,
                    trigger: { type: 'push' },
                    content: {
                        title: 'PostHog',
                        subtitle: null,
                        body: 'Chat update',
                        data: { type: 'task', taskId: 'task-a', projectId: 2 },
                        categoryIdentifier: null,
                        sound: null,
                    },
                },
            },
        }
        await act(async () => {
            AppState.currentState = 'active'
            listener(response)
        })
        await act(async () => listener(response))

        expect(screen.getAllByTestId('chat-screen')).toHaveLength(1)
        expect(screen.getByTestId('loaded-task').props.children).toBe('task-a')
        expect(screen.getByTestId('draft').props.value).toBe(preserveDraft ? 'Keep this draft' : '')
        fireEvent.press(screen.getByTestId('chat-back'))
        expect(app.getPathname()).toBe('/inbox')
        expect(screen.queryByTestId('chat-screen')).toBeNull()
    })
})
