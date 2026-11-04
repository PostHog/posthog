import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import { persistReadCache } from '@/api/readCache'
import { ReadCacheStore } from '@/api/readCacheStore'
import { useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'
import { demoAnchor, demoInsightResponse } from '@/demo/views'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import { insightQueryKey } from './items'
import { useViewsList } from './pinHooks'
import { useDeviceRecent } from './recentStore'
import { viewsQueue } from './refreshQueue'
import { useInsightScreen } from './viewHooks'

const scope = { host: 'https://example.com', projectId: 1 }
jest.mock('expo-router', () => ({ useFocusEffect: () => {}, useIsFocused: () => false }))
jest.mock('@/demo/demoMode', () => ({ ...jest.requireActual('@/demo/demoMode'), useDataMode: () => 'live' }))

let client: QueryClient
function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('cold offline Views navigation', () => {
    it('opens a saved insight from the device Recent list without loading shortcuts or metadata', async () => {
        await useAuthStore.persist.rehydrate()
        await useDeviceRecent.persist.rehydrate()
        const values = new Map<string, string>()
        const store = new ReadCacheStore({
            getItem: async (key) => values.get(key) ?? null,
            setItem: async (key, value) => {
                values.set(key, value)
            },
            removeItem: async (key) => {
                values.delete(key)
            },
        })
        const cacheScope = { ...scope, account: 'example-account' }
        const shortId = 'demo-ins-signups'
        const response = demoInsightResponse({ shortId, dashboardRef: null, override: null }, demoAnchor())
        if (!response) throw new Error('Missing demo insight')
        const snapshot = insightSnapshot(response, undefined, { readAt: Date.now(), serverNow: Date.now() })
        const source = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const session = persistReadCache(source, store, cacheScope, () => true)
        await session.ready
        source.setQueryData(insightQueryKey(scope, { shortId, dashboardRef: null, override: null }), snapshot)
        await session.flush()
        session.stop()
        source.clear()
        useDeviceRecent.getState().record(`${scope.host}|${scope.projectId}`, {
            kind: 'insight',
            ref: shortId,
            name: snapshot.name,
            viewedAt: new Date().toISOString(),
        })
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: scope.host,
            projectId: 1,
            method: 'personal_api_key',
            user: { uuid: 'example-user', distinctId: 'example-user', email: 'example@example.com', name: 'Example' },
        })
        setSessionTokens({
            kind: 'personal_api_key',
            accessToken: 'example-token',
            refreshToken: null,
            expiresAt: null,
            grantedScopes: null,
            requestedScopes: null,
        })
        setAuthProvider({
            getAuth: () => ({ ...scope, accessToken: 'example-token', session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async () => {
            throw new TypeError('Offline')
        }) as typeof fetch
        client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const restored = persistReadCache(client, store, cacheScope, () => true)
        await restored.ready
        const list = renderHook(() => useViewsList(), { wrapper })
        await waitFor(() => expect(list.result.current.recent.data?.some((item) => item.ref === shortId)).toBe(true))
        const insight = renderHook(() => useInsightScreen(shortId, { from: 'recent' }), { wrapper })
        await waitFor(() => expect(insight.result.current.insight.data?.value).toBe(snapshot.value))
        expect(insight.result.current.insight.data?.restoredFromDevice).toBe(true)
        expect(insight.result.current.refresh.status.text).toMatch(
            /^(?:Couldn't refresh\. )?Updated \d+ (?:min|h) ago$/
        )
        await act(async () => {
            insight.unmount()
            list.unmount()
        })
        restored.stop()
        client.clear()
        viewsQueue.reset()
        setAuthProvider(null)
        setSessionTokens(null)
    })
})
