import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import type { ReactElement, ReactNode } from 'react'
import { DEFAULT_NOTIFICATION_PREFERENCES, getNotificationPreferences } from '@/api/notificationPreferences'
import { useSnoozeAction, wakeSnooze } from './hooks'
import { snoozeKey } from './snoozeEntries'
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
jest.mock('@/api/notificationPreferences', () => ({
    ...jest.requireActual('@/api/notificationPreferences'),
    getNotificationPreferences: jest.fn(async () => ({ mobile_push_enabled: true, mobile_push_snooze_enabled: true })),
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn(), captureError: jest.fn() }))
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
    test.each(['finish', 'wake'])('saves a snooze while preferences are pending, then handles %s', async (next) => {
        let finishPreferences!: (preferences: typeof DEFAULT_NOTIFICATION_PREFERENCES) => void
        jest.mocked(getNotificationPreferences).mockReturnValueOnce(
            new Promise((resolve) => {
                finishPreferences = resolve
            })
        )
        const { result, unmount } = renderHook(() => useSnoozeAction('example-report'), { wrapper })
        const until = new Date(Date.now() + 3600000).toISOString()
        const scope = { host: 'https://example.com', projectId: 1 }
        const key = snoozeKey(scope, 'example-report')
        await act(async () => {
            await result.current.run({ kind: 'until', preset: 'custom', until })
        })
        expect(result.current.pending).toBe(false)
        expect(useSnoozeStore.getState().entries[key]).toMatchObject({ kind: 'until', until })
        if (next === 'wake') await act(async () => wakeSnooze(scope, 'example-report'))
        await act(async () => {
            finishPreferences(DEFAULT_NOTIFICATION_PREFERENCES)
        })
        if (next === 'finish') {
            await act(async () => {
                mockFinish?.('example-reminder')
            })
            await waitFor(() =>
                expect(useSnoozeStore.getState().entries[key]).toMatchObject({ notificationId: 'example-reminder' })
            )
        } else {
            expect(useSnoozeStore.getState().entries[key]).toBeUndefined()
            expect(Notifications.scheduleNotificationAsync).not.toHaveBeenCalled()
        }
        unmount()
    })
    test.each(['session', 'project', 'wake', 'replace'])(
        'cancels a pending reminder after the %s changes',
        async (change) => {
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
                else if (change === 'project') mockAuth.projectId = 2
                else if (change === 'wake') await wakeSnooze({ host: mockAuth.host, projectId: 1 }, 'example-report')
                else
                    useSnoozeStore.getState().put(snoozeKey({ host: mockAuth.host, projectId: 1 }, 'example-report'), {
                        kind: 'signals',
                        threshold: 5,
                        at: new Date().toISOString(),
                    })
            })
            await act(async () => {
                mockFinish?.('example-reminder')
                await pending
            })
            expect(Notifications.cancelScheduledNotificationAsync).toHaveBeenCalledWith('example-reminder')
            if (change === 'project' || change === 'replace') {
                expect(Object.values(useSnoozeStore.getState().entries)).toEqual([
                    expect.objectContaining({ kind: change === 'project' ? 'until' : 'signals' }),
                ])
                expect(Object.values(useSnoozeStore.getState().entries)[0]).not.toHaveProperty('notificationId')
            } else {
                expect(useSnoozeStore.getState().entries).toEqual({})
            }
            unmount()
        }
    )
})
