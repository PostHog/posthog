import { act, renderHook, waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import { router, usePathname } from 'expo-router'
import { AppState } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { foregroundNotificationBehavior, setViewedNotificationTask } from './foregroundNotifications'
import { acknowledgeNotificationTap, getPendingNotificationTap } from './notificationIntents'
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
jest.mock('./notificationIntents', () => ({
    getPendingNotificationTap: jest.fn(),
    acknowledgeNotificationTap: jest.fn(),
}))
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
    jest.mocked(getPendingNotificationTap).mockReturnValue(undefined)
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

test.each(['expo', 'persisted'] as const)(
    'keeps a %s cold-start tap pending until sign-in, then opens its report once',
    async (source) => {
        const response = { notification: notification(`pending-sign-in-${source}`), actionIdentifier: 'default' }
        jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
        if (source === 'persisted') {
            jest.mocked(getPendingNotificationTap).mockReturnValue({
                identifier: response.notification.request.identifier,
                data: reportData,
            })
            const stale = { notification: notification('stale-launch'), actionIdentifier: 'default' }
            stale.notification.request.content.data = { ...reportData, report_id: 'stale-report' }
            jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(stale)
        }
        useAuthStore.setState({ status: 'signed_out' })
        renderHook(useNotificationRouting)
        expect(Notifications.clearLastNotificationResponse).not.toHaveBeenCalled()
        expect(router.push).not.toHaveBeenCalled()
        expect(acknowledgeNotificationTap).not.toHaveBeenCalled()

        act(() => useAuthStore.setState({ status: 'signed_in' }))
        await waitFor(() => expect(router.push).toHaveBeenCalledWith('/report/report-1?from=push'))
        const listener = jest.mocked(Notifications.addNotificationResponseReceivedListener).mock.calls[0]?.[0]
        if (!listener) {
            throw new Error('Notification tap listener was not registered')
        }
        act(() => listener(response))
        expect(router.push).toHaveBeenCalledTimes(1)
        expect(Notifications.clearLastNotificationResponse).toHaveBeenCalledTimes(source === 'expo' ? 1 : 0)
        expect(acknowledgeNotificationTap).toHaveBeenCalledWith(response.notification.request.identifier)
        expect(acknowledgeNotificationTap).toHaveBeenCalledTimes(2)
    }
)

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

test.each(['same-account', 'changed-account', 'newer-tap'] as const)(
    'acknowledges a task tap only after routing: %s',
    async (scenario) => {
        let resolveLookup!: (value: { found: true; reportId: null }) => void
        jest.mocked(findTask).mockReturnValue(
            new Promise((resolve) => {
                resolveLookup = resolve
            })
        )
        const response = { notification: notification(`changed-account-${scenario}`), actionIdentifier: 'default' }
        response.notification.request.content.data = { taskId: 'task-1', projectId: 2 }
        jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
        renderHook(useNotificationRouting)
        expect(acknowledgeNotificationTap).not.toHaveBeenCalled()
        expect(Notifications.clearLastNotificationResponse).not.toHaveBeenCalled()
        if (scenario === 'changed-account') {
            act(() => useAuthStore.setState({ host: 'https://another.example.com' }))
        } else if (scenario === 'newer-tap') {
            jest.mocked(getPendingNotificationTap).mockReturnValue({ identifier: 'newer-tap', data: reportData })
        }
        await act(async () => resolveLookup({ found: true, reportId: null }))
        expect(router.push).toHaveBeenCalledTimes(scenario === 'same-account' ? 1 : 0)
        expect(acknowledgeNotificationTap).toHaveBeenCalledTimes(scenario === 'same-account' ? 1 : 0)
        expect(router.replace).not.toHaveBeenCalled()
    }
)

test.each(['before', 'after'] as const)(
    'ignores older Expo replay %s the newest response across sign-in',
    async (replayOrder) => {
        const older = { notification: notification(`older-${replayOrder}`), actionIdentifier: 'default' }
        older.notification.request.content.data = { ...reportData, report_id: 'older-report' }
        const latest = { notification: notification(`latest-${replayOrder}`), actionIdentifier: 'default' }
        latest.notification.request.content.data = { ...reportData, report_id: 'latest-report' }
        const latestId = latest.notification.request.identifier
        jest.mocked(getPendingNotificationTap).mockReturnValue({
            identifier: latestId,
            data: latest.notification.request.content.data,
        })
        jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(
            replayOrder === 'before' ? older : latest
        )
        useAuthStore.setState({ status: 'signed_out' })
        renderHook(useNotificationRouting)
        expect(router.push).not.toHaveBeenCalled()

        act(() => useAuthStore.setState({ status: 'signed_in' }))
        const listener = jest.mocked(Notifications.addNotificationResponseReceivedListener).mock.calls[0]?.[0]
        if (!listener) {
            throw new Error('Notification tap listener was not registered')
        }
        act(() => {
            if (replayOrder === 'before') {
                listener(older)
            }
            listener(latest)
            if (replayOrder === 'after') {
                listener(older)
            }
        })
        await waitFor(() => expect(router.push).toHaveBeenCalledWith('/report/latest-report?from=push'))
        act(() => listener(older))
        expect(router.push).toHaveBeenCalledTimes(1)
        expect(acknowledgeNotificationTap).not.toHaveBeenCalledWith(older.notification.request.identifier)
    }
)

test('ignores Expo responses when the supported native tap store is empty', async () => {
    const response = { notification: notification('untrusted-expo'), actionIdentifier: 'default' }
    jest.mocked(getPendingNotificationTap).mockReturnValue(null)
    jest.mocked(Notifications.getLastNotificationResponse).mockReturnValue(response)
    renderHook(useNotificationRouting)
    const listener = jest.mocked(Notifications.addNotificationResponseReceivedListener).mock.calls[0]?.[0]
    if (!listener) {
        throw new Error('Notification tap listener was not registered')
    }
    await act(async () => listener(response))
    expect(router.push).not.toHaveBeenCalled()
    expect(acknowledgeNotificationTap).not.toHaveBeenCalled()
})
