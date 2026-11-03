import { act, renderHook, waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import { router, usePathname } from 'expo-router'
import { AppState } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { foregroundNotificationBehavior, setViewedNotificationTask } from './foregroundNotifications'
import { findTask } from './taskLookup'
import { useNotificationRouting } from './useNotificationRouting'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({
    getLastNotificationResponse: jest.fn(),
    clearLastNotificationResponse: jest.fn(),
    addNotificationResponseReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
}))
jest.mock('expo-router', () => ({
    router: { push: jest.fn(), navigate: jest.fn(), replace: jest.fn() },
    useRootNavigationState: () => ({ key: 'root' }),
    useNavigationContainerRef: () => mockNavigation,
    usePathname: jest.fn(() => '/inbox'),
}))
jest.mock('@/demo/demoMode', () => ({ useDemoMode: { getState: () => ({ enabled: false }) } }))
jest.mock('./pushSupport', () => ({ notificationsSupported: () => true }))
jest.mock('./taskLookup', () => ({ findTask: jest.fn() }))

const reportData = { type: 'report', report_id: 'report-1', project_id: 2 }
const mockNavigation = { getCurrentRoute: jest.fn(() => ({ name: 'inbox' })) }
function notification(identifier: string): Notifications.Notification {
    return {
        date: Date.now(),
        request: {
            identifier,
            trigger: { type: 'push' },
            content: {
                title: 'PostHog',
                subtitle: null,
                body: 'Report update',
                data: reportData,
                categoryIdentifier: null,
                sound: null,
            },
        },
    }
}

beforeEach(() => {
    jest.clearAllMocks()
    jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(null)
    jest.mocked(usePathname).mockReturnValue('/inbox')
    mockNavigation.getCurrentRoute.mockReturnValue({ name: 'inbox' })
    setViewedNotificationTask(null)
    AppState.currentState = 'active'
    useAuthStore.setState({
        status: 'signed_in',
        host: 'https://app.example.com',
        projectId: 2,
        user: { uuid: 'routing-user' } as NonNullable<ReturnType<typeof useAuthStore.getState>['user']>,
        projects: [],
    })
})

test('keeps a cold-start tap pending until sign-in, then opens its report once', async () => {
    const response = { notification: notification('pending-sign-in'), actionIdentifier: 'default' }
    jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
    useAuthStore.setState({ status: 'signed_out' })
    renderHook(useNotificationRouting)
    expect(Notifications.clearLastNotificationResponse).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()

    act(() => useAuthStore.setState({ status: 'signed_in' }))
    await waitFor(() => expect(router.push).toHaveBeenCalledWith('/report/report-1?from=push'))
    const listener = jest.mocked(Notifications.addNotificationResponseReceivedListener).mock.calls[0]?.[0]
    if (!listener) {
        throw new Error('Notification tap listener was not registered')
    }
    act(() => listener(response))
    expect(router.push).toHaveBeenCalledTimes(1)
    expect(Notifications.clearLastNotificationResponse).toHaveBeenCalledTimes(1)
})

test('suppresses the viewed report only while that route is on screen', () => {
    jest.mocked(usePathname).mockReturnValue('/report/report-1')
    const hook = renderHook(useNotificationRouting)
    expect(foregroundNotificationBehavior(notification('viewed')).shouldShowBanner).toBe(false)

    jest.mocked(usePathname).mockReturnValue('/inbox')
    hook.rerender({})
    expect(foregroundNotificationBehavior(notification('elsewhere')).shouldShowBanner).toBe(true)

    jest.mocked(usePathname).mockReturnValue('/report/report-1')
    hook.rerender({})
    hook.unmount()
    expect(foregroundNotificationBehavior(notification('unmounted')).shouldShowBanner).toBe(true)
})

test('opens a standalone task chat from a notification', async () => {
    jest.mocked(findTask).mockResolvedValue({ found: true, reportId: null })
    const response = { notification: notification('standalone-chat'), actionIdentifier: 'default' }
    response.notification.request.content.data = { taskId: 'task-1', projectId: 2 }
    jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
    renderHook(useNotificationRouting)
    await waitFor(() => expect(router.push).toHaveBeenCalledWith('/chat?taskId=task-1&from=push'))
})

test('does not route a task lookup into an account that signed in while it was pending', async () => {
    let resolveLookup!: (value: { found: true; reportId: null }) => void
    jest.mocked(findTask).mockReturnValue(
        new Promise((resolve) => {
            resolveLookup = resolve
        })
    )
    const response = { notification: notification('changed-account'), actionIdentifier: 'default' }
    response.notification.request.content.data = { taskId: 'task-1', projectId: 2 }
    jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
    renderHook(useNotificationRouting)
    act(() => useAuthStore.setState({ host: 'https://another.example.com' }))
    await act(async () => resolveLookup({ found: true, reportId: null }))
    expect(router.push).not.toHaveBeenCalled()
    expect(router.replace).not.toHaveBeenCalled()
})
