import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import type { ReactNode } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { DEFAULT_NOTIFICATION_PREFERENCES, getNotificationPreferences } from '@/api/notificationPreferences'
import { captureError } from '@/lib/analytics'

import { useSnoozeReminderPreferences } from './useSnoozeReminderPreferences'

jest.mock('@/api/notificationPreferences', () => ({
    ...jest.requireActual('@/api/notificationPreferences'),
    getNotificationPreferences: jest.fn(),
}))
jest.mock('@/auth/authStore', () => ({
    useAuthStore: (select: (state: unknown) => unknown) =>
        select({ signedIn: true, host: 'https://example.com', user: { uuid: 'user-1' } }),
}))
jest.mock('@/demo/demoMode', () => ({
    useDemoMode: (select: (state: unknown) => unknown) => select({ enabled: false }),
}))
jest.mock('@/lib/analytics', () => ({ captureError: jest.fn() }))
jest.mock('expo-notifications', () => ({
    getAllScheduledNotificationsAsync: jest.fn(),
    cancelScheduledNotificationAsync: jest.fn(),
}))

describe('reminder preference refresh', () => {
    afterEach(() => jest.restoreAllMocks())

    test('retries failed native cancellation when foreground preferences are unchanged', async () => {
        const clock = jest.spyOn(Date, 'now').mockReturnValue(1000)
        let onStateChange: ((state: AppStateStatus) => void) | undefined
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
            onStateChange = listener
            return { remove: jest.fn() }
        })
        jest.mocked(getNotificationPreferences).mockResolvedValue({
            ...DEFAULT_NOTIFICATION_PREFERENCES,
            mobile_push_snooze_enabled: false,
        })
        const pending = new Set(['snooze-1'])
        jest.mocked(Notifications.getAllScheduledNotificationsAsync).mockImplementation(async () =>
            [...pending].map((identifier) => ({
                identifier,
                trigger: null,
                content: {
                    title: null,
                    subtitle: null,
                    body: null,
                    categoryIdentifier: null,
                    sound: null,
                    threadIdentifier: null,
                    data: { notificationKind: 'snooze_reminder' },
                },
            }))
        )
        jest.mocked(Notifications.cancelScheduledNotificationAsync)
            .mockRejectedValueOnce(new Error('native cancellation failed'))
            .mockImplementation(async (id) => {
                pending.delete(id)
            })
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const { unmount } = renderHook(useSnoozeReminderPreferences, {
            wrapper: ({ children }: { children: ReactNode }) => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            ),
        })
        await waitFor(() => expect(captureError).toHaveBeenCalled())
        expect(pending.size).toBe(1)
        clock.mockReturnValue(2000)
        act(() => onStateChange?.('active'))
        await waitFor(() => expect(pending.size).toBe(0))
        unmount()
        client.clear()
    })
})
