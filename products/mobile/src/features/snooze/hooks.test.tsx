import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import type { ReactElement, ReactNode } from 'react'
import { useSnoozeAction } from './hooks'
import { useSnoozeStore } from './snoozeStore'

let mockEndSession: (() => Promise<void>) | undefined
let mockFinish: ((id: string) => void) | undefined
const mockAuth = { signedIn: true, host: 'https://example.com', projectId: 1 }
jest.mock('@/auth/authStore', () => ({
    addSessionEndTask: (callback: () => Promise<void>) => {
        mockEndSession = callback
    },
    useAuthStore: { getState: () => mockAuth },
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 1 }) }))
jest.mock('@/demo/demoMode', () => ({
    useDemoMode: (selector: (s: unknown) => unknown) => selector({ enabled: false, snooze: jest.fn() }),
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('expo-notifications', () => ({
    getPermissionsAsync: jest.fn(async () => ({ granted: true })),
    scheduleNotificationAsync: jest.fn(
        () =>
            new Promise<string>((resolve) => {
                mockFinish = resolve
            })
    ),
    cancelScheduledNotificationAsync: jest.fn(async () => undefined),
    SchedulableTriggerInputTypes: { DATE: 'date' },
}))
const client = new QueryClient()
function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
describe('snooze lifecycle', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockAuth.projectId = 1
        useSnoozeStore.getState().clear()
    })
    test.each(['session', 'project'])('cancels a pending reminder after the %s changes', async (change) => {
        const { result, unmount } = renderHook(() => useSnoozeAction('example-report'), { wrapper })
        let pending: Promise<void> = Promise.resolve()
        await act(async () => {
            pending = result.current.run({
                kind: 'until',
                preset: 'custom',
                until: new Date(Date.now() + 3600000).toISOString(),
            })
        })
        expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledTimes(1)
        await act(async () => {
            if (change === 'session') await mockEndSession?.()
            else mockAuth.projectId = 2
        })
        await act(async () => {
            mockFinish?.('example-reminder')
            await pending
        })
        expect(Notifications.cancelScheduledNotificationAsync).toHaveBeenCalledWith('example-reminder')
        expect(useSnoozeStore.getState().entries).toEqual({})
        unmount()
    })
})
