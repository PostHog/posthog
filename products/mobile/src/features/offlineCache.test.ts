import { act, waitFor } from '@testing-library/react-native'
import { AppState } from 'react-native'

let mockOwner = { host: 'https://example.com', userUuid: 'user-1' }
let mockTokens = true
let mockReadGate: Promise<void> | undefined
const mockDigestGates = new Map<string, Promise<void>>()
const mockValues = new Map<string, string>()
const mockReads: string[] = []
const mockEndTasks = new Set<() => Promise<void>>()

jest.mock('expo-crypto', () => ({
    CryptoDigestAlgorithm: { SHA256: 'SHA256' },
    digestStringAsync: async (_algorithm: string, input: string) => {
        await mockDigestGates.get(input)
        return input.replace(/\W/g, '_')
    },
}))
jest.mock('@/auth/tokens', () => ({
    getSessionTokens: () => (mockTokens ? {} : null),
    getSessionIdentity: () => mockOwner,
}))
jest.mock('@/auth/authStore', () => {
    const { create } = jest.requireActual<typeof import('zustand')>('zustand')
    return {
        useAuthStore: create(() => ({
            signedIn: true,
            host: 'https://example.com',
            user: { uuid: 'user-1' },
            projectId: 1,
        })),
        addSessionEndTask: (task: () => Promise<void>) => {
            mockEndTasks.add(task)
            return () => {
                mockEndTasks.delete(task)
            }
        },
    }
})
jest.mock('@/features/views/viewsCache', () => {
    const { create } = jest.requireActual<typeof import('zustand')>('zustand')
    return { useItemErrors: create(() => ({ errors: {} })) }
})
jest.mock('@/features/views/useViewsAccess', () => {
    const { create } = jest.requireActual<typeof import('zustand')>('zustand')
    return { useScopeErrorStore: create(() => ({ reported: { views: null, errors: null, replay: null } })) }
})
jest.mock('@/lib/secureStorage', () => ({
    secureStorage: {
        getItem: async (key: string) => {
            mockReads.push(key)
            await mockReadGate
            return mockValues.get(key) ?? null
        },
        setItem: async (key: string, value: string) => {
            mockValues.set(key, value)
        },
        removeItem: async (key: string) => {
            mockValues.delete(key)
        },
    },
}))

import { ApiError } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { useAuthStore } from '@/auth/authStore'
import { useScopeErrorStore } from '@/features/views/useViewsAccess'
import { useItemErrors } from '@/features/views/viewsCache'
import { installOfflineCache } from './offlineCache'

function account(user = 'user-1', host = 'https://example.com'): string {
    return `mobile-read-cache-v1-${JSON.stringify([host, user]).replace(/\W/g, '_')}`
}
function seed(projectId: number, user = 'user-1'): readonly unknown[] {
    const key = ['views', 'https://example.com', projectId, 'web', '-']
    mockValues.set(
        `${account(user)}.${projectId}`,
        JSON.stringify([{ key, updatedAt: Date.now() - 1000, data: { metrics: [], readAt: Date.now() - 1000 } }])
    )
    const index = `${account(user)}.scopes`
    const scopes: string[] = JSON.parse(mockValues.get(index) ?? '[]')
    mockValues.set(index, JSON.stringify([...new Set([...scopes, `${account(user)}.${projectId}`])]))
    return key
}

describe('authenticated offline-cache lifecycle', () => {
    beforeEach(() => {
        mockOwner = { host: 'https://example.com', userUuid: 'user-1' }
        mockTokens = true
        mockReadGate = undefined
        mockDigestGates.clear()
        mockValues.clear()
        mockReads.length = 0
        useScopeErrorStore.setState({
            reported: { views: null, errors: null, replay: null, inbox: null, experiments: null },
        })
        queryClient.clear()
        useItemErrors.setState({ errors: {} })
        useAuthStore.setState({
            signedIn: true,
            host: 'https://example.com',
            user: { uuid: 'user-1', distinctId: 'user-1', email: 'example@example.com', name: 'Example' },
            projectId: 1,
        })
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: () => undefined })
    })
    afterEach(() => {
        jest.restoreAllMocks()
        queryClient.clear()
    })

    test.each(['digest', 'load'])(
        'does not hydrate project 1 after switching while its %s is pending',
        async (stage) => {
            const first = seed(1)
            const second = seed(2)
            let finish!: () => void
            const gate = new Promise<void>((resolve) => {
                finish = resolve
            })
            if (stage === 'digest') mockDigestGates.set(JSON.stringify(['https://example.com', 'user-1']), gate)
            else mockReadGate = gate
            const stop = installOfflineCache()
            await act(async () => {
                useAuthStore.setState({ projectId: 2 })
                finish()
            })
            await waitFor(() => expect(queryClient.getQueryData(second)).toBeDefined())
            expect(queryClient.getQueryData(first)).toBeUndefined()
            stop()
        }
    )

    it('requires the secure owner to match before reading cached data', async () => {
        const key = seed(1)
        mockOwner = { host: 'https://example.com', userUuid: 'other-user' }
        const stop = installOfflineCache()
        await act(async () => undefined)
        expect(queryClient.getQueryData(key)).toBeUndefined()
        stop()
    })

    it('purges the departing account after delayed hydration and leaves another account intact', async () => {
        const key = seed(1)
        seed(1, 'user-2')
        let finish!: () => void
        mockReadGate = new Promise<void>((resolve) => {
            finish = resolve
        })
        const stop = installOfflineCache()
        await act(async () => undefined)
        mockTokens = false
        const cleanup = Promise.all([...mockEndTasks].map((task) => task()))
        finish()
        await cleanup
        expect(queryClient.getQueryData(key)).toBeUndefined()
        expect(mockValues.has(`${account()}.1`)).toBe(false)
        expect(mockValues.has(`${account('user-2')}.1`)).toBe(true)
        stop()
    })
    it('does not hydrate the previous account into the next account while its read is pending', async () => {
        const key = seed(1)
        mockValues.set(
            `${account('user-2')}.1`,
            JSON.stringify([
                { key, updatedAt: Date.now() - 500, data: { metrics: [{ key: 'user-2' }], readAt: Date.now() - 500 } },
            ])
        )
        let finish!: () => void
        mockReadGate = new Promise<void>((resolve) => {
            finish = resolve
        })
        const stop = installOfflineCache()
        await waitFor(() => expect(mockReads).toContain(`${account()}.1`))
        await act(async () => {
            mockOwner = { host: 'https://example.com', userUuid: 'user-2' }
            useAuthStore.setState({
                user: { uuid: 'user-2', distinctId: 'user-2', email: 'other@example.com', name: 'Other' },
            })
            finish()
        })
        await waitFor(() => expect(queryClient.getQueryData(key)).toMatchObject({ metrics: [{ key: 'user-2' }] }))
        stop()
    })
    it('does not restore an inbox refused before the account digest finishes', async () => {
        const key = ['read-inbox', 'https://example.com', 1]
        mockValues.set(
            `${account()}.1`,
            JSON.stringify([
                { key, updatedAt: Date.now() - 1000, data: { items: [], sourceUpdatedAt: Date.now() - 1000 } },
            ])
        )
        let finish!: () => void
        mockDigestGates.set(
            JSON.stringify(['https://example.com', 'user-1']),
            new Promise<void>((resolve) => {
                finish = resolve
            })
        )
        const stop = installOfflineCache()
        await queryClient
            .fetchQuery({
                queryKey: ['signals', 'https://example.com', 1, 'inbox'],
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
                retry: false,
            })
            .catch(() => undefined)
        finish()
        await waitFor(() => expect(JSON.parse(mockValues.get(`${account()}.1`) ?? '[]')).toEqual([]))
        expect(queryClient.getQueryData(key)).toBeUndefined()
        stop()
    })

    test.each(['view-error', 'query-error'] as const)(
        'evicts the original project after a late %s across a project switch',
        async (source) => {
            const first = seed(1)
            const second = seed(2)
            let stop = installOfflineCache()
            await waitFor(() => expect(queryClient.getQueryData(first)).toBeDefined())
            let deny = (): void => undefined
            const request =
                source === 'query-error'
                    ? queryClient
                          .fetchQuery({
                              queryKey: first,
                              staleTime: 0,
                              queryFn: () =>
                                  new Promise<never>((_resolve, reject) => {
                                      deny = () => reject(new ApiError(403, {}))
                                  }),
                              retry: false,
                          })
                          .catch(() => undefined)
                    : Promise.resolve()
            await act(async () => {
                useAuthStore.setState({ projectId: 2 })
            })
            await waitFor(() => expect(queryClient.getQueryData(second)).toBeDefined())
            await act(async () => {
                if (source === 'view-error') {
                    queryClient.removeQueries({ queryKey: first })
                    useItemErrors.setState({ errors: { [JSON.stringify(first)]: 'no_access' } })
                }
                deny()
                await request
            })
            await waitFor(() => expect(mockValues.has(`${account()}.1`)).toBe(false))
            expect(queryClient.getQueryData(second)).toBeDefined()
            stop()
            queryClient.clear()
            useItemErrors.setState({ errors: {} })
            useAuthStore.setState({ projectId: 1 })
            stop = installOfflineCache()
            await act(async () => undefined)
            expect(queryClient.getQueryData(first)).toBeUndefined()
            stop()
        }
    )

    it('clears Views from unvisited saved projects after a scope denial and preserves inbox and other accounts', async () => {
        const first = seed(1)
        const unvisited = seed(2)
        seed(2, 'user-2')
        const inbox = ['read-inbox', 'https://example.com', 2]
        const saved = JSON.parse(mockValues.get(`${account()}.2`) ?? '[]')
        saved.push({
            key: inbox,
            updatedAt: Date.now() - 1000,
            data: { items: [], sourceUpdatedAt: Date.now() - 1000 },
        })
        mockValues.set(`${account()}.2`, JSON.stringify(saved))
        let stop = installOfflineCache()
        await waitFor(() => expect(queryClient.getQueryData(first)).toBeDefined())
        useScopeErrorStore.setState({
            reported: { views: 'insights:read', errors: null, replay: null, inbox: null, experiments: null },
        })
        await waitFor(() => expect(mockValues.get(`${account()}.2`)).not.toContain('"views"'))
        stop()
        queryClient.clear()
        useScopeErrorStore.setState({
            reported: { views: null, errors: null, replay: null, inbox: null, experiments: null },
        })
        useAuthStore.setState({ projectId: 2 })
        stop = installOfflineCache()
        await waitFor(() => expect(queryClient.getQueryData(inbox)).toBeDefined())
        expect(queryClient.getQueryData(unvisited)).toBeUndefined()
        expect(mockValues.get(`${account('user-2')}.2`)).toContain('"views"')
        stop()
    })

    it('does not rehydrate views when the existing access gate reports a missing scope', async () => {
        const key = seed(1)
        useScopeErrorStore.setState({
            reported: { views: 'insights:read', errors: null, replay: null, inbox: null, experiments: null },
        })
        const stop = installOfflineCache()
        await waitFor(() => expect(JSON.parse(mockValues.get(`${account()}.1`) ?? '[]')).toEqual([]))
        expect(queryClient.getQueryData(key)).toBeUndefined()
        stop()
    })
})
