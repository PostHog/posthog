import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import { getNetworkStateAsync } from 'expo-network'
import type { ReactElement, ReactNode } from 'react'
import { AppState } from 'react-native'
import { setAuthProvider } from '@/api/client'
import { useAuthStore } from '@/auth/authStore'
import { useChatList } from '@/features/chats/hooks'
import { useInboxItems } from '@/features/inbox/hooks'
import { useReport } from '@/features/report/hooks'
import { useBrowseDashboards } from '@/features/views/browseHooks'
import { usePins, useRecentViews } from '@/features/views/pinHooks'
import { viewsQueue } from '@/features/views/refreshQueue'
import { useDashboardScreen } from '@/features/views/viewHooks'
import { reportFixture } from '@/model/adapters/testFixtures'
import type { QueryState } from '@/model/types'

import { useConnectivity } from './connectivity'

jest.mock('expo-notifications', () => ({}))
jest.mock('expo-router', () => {
    const { useEffect } = jest.requireActual<typeof import('react')>('react')
    return {
        useFocusEffect: (effect: () => undefined | (() => void)) => useEffect(effect, [effect]),
        useIsFocused: () => true,
    }
})
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/demo/demoMode', () => ({ ...jest.requireActual('@/demo/demoMode'), useDataMode: () => 'live' }))
jest.mock('@/features/views/useViewsAccess', () => ({
    ...jest.requireActual('@/features/views/useViewsAccess'),
    useViewsAccess: () => ({ state: 'ok', missingScope: null }),
}))

const NO_PINS = new Set<string>()

describe('paused reads without cached data', () => {
    beforeEach(() => {
        viewsQueue.reset()
        AppState.currentState = 'active'
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: jest.fn() })
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://app.example.com',
            projectId: 2,
            user: {
                id: 7,
                uuid: 'synthetic-user',
                distinctId: 'synthetic-user',
                email: 'person@example.com',
                name: 'Example',
            },
        })
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'fake', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        jest.mocked(getNetworkStateAsync).mockImplementation(() => new Promise(() => undefined))
        useConnectivity.setState({ status: 'offline' })
        onlineManager.setOnline(false)
        globalThis.fetch = jest.fn(async (url: string) => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () =>
                JSON.stringify(
                    url.includes('/dashboards/1/')
                        ? { id: 1, name: 'Example dashboard', tiles: [] }
                        : url.endsWith('/signals/reports/offline-report/')
                          ? reportFixture({ id: 'offline-report' })
                          : url.includes('/today/')
                            ? { lead: '', evidence: [], impact_sentence: '', impact_numbers: [], last_seen: null }
                            : url.endsWith('/signals/')
                              ? { signals: [] }
                              : { count: 0, next: null, results: [] }
                ),
        })) as unknown as typeof fetch
    })
    afterEach(() => {
        viewsQueue.reset()
        onlineManager.setOnline(true)
        useConnectivity.setState({ status: 'unknown' })
        setAuthProvider(null)
        jest.restoreAllMocks()
    })

    test.each<[string, () => QueryState<unknown>]>([
        ['inbox', () => useInboxItems()],
        ['chats', () => useChatList()],
        ['report', () => useReport('offline-report')],
        ['pinned views', () => usePins().pins],
        ['recent views', () => useRecentViews(NO_PINS).recent],
        ['browse dashboards', () => useBrowseDashboards()],
        ['dashboard detail', () => useDashboardScreen('1', { from: 'browse' }).dashboard],
    ])(
        '%s shows a connection state, resumes automatically, and retains loaded data offline',
        async (_name, useRead) => {
            const client = new QueryClient({
                defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } },
            })
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            )
            const { result, unmount } = renderHook(() => useRead(), { wrapper })
            try {
                expect(result.current.data).toBeUndefined()
                expect(result.current.isLoading).toBe(false)
                expect(result.current.error?.message).toContain('Your data will load when your connection returns')
                expect(globalThis.fetch).not.toHaveBeenCalled()
                await act(async () => {
                    useConnectivity.setState({ status: 'connected' })
                    onlineManager.setOnline(true)
                })
                await waitFor(() => expect(result.current.data).toBeDefined())
                const loaded = result.current.data
                expect(result.current.isError).toBe(false)
                await act(async () => {
                    useConnectivity.setState({ status: 'offline' })
                    onlineManager.setOnline(false)
                })
                expect(result.current.data).toEqual(loaded)
                expect(result.current.isError).toBe(false)
                expect(result.current.isLoading).toBe(false)
            } finally {
                unmount()
                client.clear()
            }
        }
    )
})
