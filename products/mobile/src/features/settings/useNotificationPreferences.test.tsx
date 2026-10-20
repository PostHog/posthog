import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactNode } from 'react'

import {
    DEFAULT_NOTIFICATION_PREFERENCES,
    getNotificationPreferences,
    setNotificationPreference,
} from '@/api/notificationPreferences'
import { useNotificationPreferences } from './useNotificationPreferences'

jest.mock('@/api/notificationPreferences', () => ({
    ...jest.requireActual('@/api/notificationPreferences'),
    getNotificationPreferences: jest.fn(),
    setNotificationPreference: jest.fn(),
}))
jest.mock('@/auth/authStore', () => ({
    useAuthStore: (select: (state: unknown) => unknown) =>
        select({ signedIn: true, host: 'https://example.com', user: { uuid: 'user-1' } }),
}))
let mockMode = 'live'
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => mockMode }))

function setup(): ReturnType<typeof renderHook<ReturnType<typeof useNotificationPreferences>, unknown>> {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    return renderHook(useNotificationPreferences, {
        wrapper: ({ children }: { children: ReactNode }) => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
    })
}

describe('notification preferences', () => {
    beforeEach(() => {
        jest.resetAllMocks()
        mockMode = 'live'
    })

    test('loads saved preferences and persists a changed category', async () => {
        let resolveLoad!: (value: typeof DEFAULT_NOTIFICATION_PREFERENCES) => void
        jest.mocked(getNotificationPreferences).mockReturnValue(
            new Promise((resolve) => {
                resolveLoad = resolve
            })
        )
        const saved = { ...DEFAULT_NOTIFICATION_PREFERENCES, mobile_push_tasks_enabled: false }
        jest.mocked(setNotificationPreference).mockResolvedValue(saved)
        const { result } = setup()
        expect(result.current.loading).toBe(true)
        expect(result.current.preferences).toBeUndefined()
        await act(async () => resolveLoad(DEFAULT_NOTIFICATION_PREFERENCES))
        await waitFor(() => expect(result.current.preferences).toEqual(DEFAULT_NOTIFICATION_PREFERENCES))
        await act(async () => result.current.change('mobile_push_tasks_enabled', false))
        expect(setNotificationPreference).toHaveBeenCalledWith('mobile_push_tasks_enabled', false)
        await waitFor(() => expect(result.current.preferences).toEqual(saved))
    })

    test('keeps saved values after a failed save and guards overlapping changes', async () => {
        jest.mocked(getNotificationPreferences).mockResolvedValue(DEFAULT_NOTIFICATION_PREFERENCES)
        let rejectSave!: (error: Error) => void
        jest.mocked(setNotificationPreference).mockReturnValue(
            new Promise((_, reject) => {
                rejectSave = reject
            })
        )
        const { result } = setup()
        await waitFor(() => expect(result.current.loading).toBe(false))
        let saving!: Promise<void>
        act(() => {
            saving = result.current.change('mobile_push_enabled', false)
        })
        expect(result.current.saving).toBe(true)
        await act(async () => result.current.change('mobile_push_reports_enabled', false))
        expect(setNotificationPreference).toHaveBeenCalledTimes(1)
        await act(async () => {
            rejectSave(new Error('offline'))
            await saving
        })
        expect(result.current.preferences).toEqual(DEFAULT_NOTIFICATION_PREFERENCES)
        expect(result.current.saveError).toContain("Couldn't save")
        expect(result.current.saving).toBe(false)
    })

    test('demo changes stay on the device without account requests', async () => {
        mockMode = 'demo'
        const { result } = setup()
        await act(async () => result.current.change('mobile_push_enabled', false))
        expect(result.current.preferences?.mobile_push_enabled).toBe(false)
        expect(getNotificationPreferences).not.toHaveBeenCalled()
        expect(setNotificationPreference).not.toHaveBeenCalled()
    })

    test('retries a failed load', async () => {
        jest.mocked(getNotificationPreferences)
            .mockRejectedValueOnce(new Error('offline'))
            .mockResolvedValue(DEFAULT_NOTIFICATION_PREFERENCES)
        const { result } = setup()
        await waitFor(() => expect(result.current.loadError).toBe(true))
        act(() => result.current.retry())
        await waitFor(() => expect(result.current.preferences).toEqual(DEFAULT_NOTIFICATION_PREFERENCES))
        expect(result.current.loadError).toBe(false)
    })
})
