import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import { createElement, type ReactNode } from 'react'

import type { PaginatedApi } from '@/api/reports'
import { createShortcut, deleteShortcut, type FileSystemShortcutApi } from '@/api/shortcuts'
import { useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'

import { pinView, unpinView, usePinActions } from './pinHooks'
import { useViewsContext } from './useViewsContext'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/api/shortcuts', () => ({
    ...jest.requireActual<typeof import('@/api/shortcuts')>('@/api/shortcuts'),
    createShortcut: jest.fn(),
    deleteShortcut: jest.fn(),
}))

jest.mock('./useViewsContext', () => ({ useViewsContext: jest.fn() }))

const created: FileSystemShortcutApi = {
    id: '0192f3a0-0000-7000-8000-000000000001',
    path: 'Growth',
    type: 'dashboard',
    ref: '12',
    href: '/dashboard/12',
    order: 1,
    created_at: '2026-10-14T12:00:00Z',
}

describe('pin writes', () => {
    beforeEach(() => jest.clearAllMocks())

    test('an unpin made while the pin saves waits for it and deletes the row it created', async () => {
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
        const listKey = ['views', 'https://us.example.com', 1, 'shortcuts']
        client.setQueryData<PaginatedApi<FileSystemShortcutApi>>(listKey, { count: 0, next: null, results: [] })
        let save: (row: FileSystemShortcutApi) => void = () => undefined
        jest.mocked(createShortcut).mockReturnValue(
            new Promise((resolve) => {
                save = resolve
            })
        )
        jest.mocked(deleteShortcut).mockResolvedValue()
        const list = { client, listKey, demo: false, isCurrent: () => true }
        const target = { kind: 'dashboard' as const, id: 12, name: 'Growth' }

        const pinned = pinView(list, target, 'swipe')
        const unpinned = unpinView(list, target, 'swipe')
        await Promise.resolve()
        expect(deleteShortcut).not.toHaveBeenCalled()

        save(created)
        await Promise.all([pinned, unpinned])

        expect(deleteShortcut).toHaveBeenCalledWith(created.id)
        expect(client.getQueryData<PaginatedApi<FileSystemShortcutApi>>(listKey)?.results).toEqual([])
    })

    test.each(['project', 'session'] as const)('captures the %s before enqueuing a pin action', async (change) => {
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
        const scope = { host: 'https://us.example.com', projectId: 1 }
        const listKey = ['views', scope.host, scope.projectId, 'shortcuts']
        client.setQueryData<PaginatedApi<FileSystemShortcutApi>>(listKey, { count: 0, next: null, results: [] })
        jest.mocked(useViewsContext).mockReturnValue({
            mode: 'live',
            identity: 'example-session',
            scope,
            dataScope: `${scope.host}|${scope.projectId}`,
            ready: false,
            access: { state: 'ok', missingScope: null },
            item: { client, scope, demo: false },
        })
        const previousAuth = useAuthStore.getState()
        // Project scopes normalize a trailing slash on the configured host.
        useAuthStore.setState({ status: 'signed_in', signedIn: true, host: `${scope.host}/`, projectId: 1 })
        let finish: (row: FileSystemShortcutApi) => void = () => undefined
        jest.mocked(createShortcut).mockReturnValue(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        const { result, unmount } = renderHook(() => usePinActions(), {
            wrapper: ({ children }: { children: ReactNode }) =>
                createElement(QueryClientProvider, { client }, children),
        })
        const target = { kind: 'dashboard' as const, id: 12, name: 'Growth' }
        let running!: Promise<void>
        let queued!: Promise<void>
        await act(async () => {
            running = result.current.pin(target, 'header')
            queued = result.current.unpin(target, 'header')
            await Promise.resolve()
        })
        expect(createShortcut).toHaveBeenCalledTimes(1)
        const assertions = Promise.all([
            expect(running).rejects.toMatchObject({ name: 'AbortError' }),
            expect(queued).rejects.toMatchObject({ name: 'AbortError' }),
        ])
        await act(async () => {
            if (change === 'project') {
                useAuthStore.setState({ projectId: 2 })
            } else {
                setSessionTokens(null)
            }
            client.clear()
            finish(created)
            await assertions
        })
        expect(deleteShortcut).not.toHaveBeenCalled()
        expect(client.getQueryData(listKey)).toBeUndefined()
        unmount()
        useAuthStore.setState(previousAuth)
    })

    test.each(['pin', 'unpin'] as const)('stops %s continuations when the selected project changes', async (first) => {
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
        const listKey = ['views', 'https://us.example.com', 1, 'shortcuts']
        client.setQueryData<PaginatedApi<FileSystemShortcutApi>>(listKey, {
            count: first === 'unpin' ? 1 : 0,
            next: null,
            results: first === 'unpin' ? [created] : [],
        })
        let finish: () => void = () => undefined
        jest.mocked(createShortcut).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finish = () => resolve(created)
                })
        )
        jest.mocked(deleteShortcut).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finish = () => resolve()
                })
        )
        let current = true
        const list = { client, listKey, demo: false, isCurrent: () => current }
        const target = { kind: 'dashboard' as const, id: 12, name: 'Growth' }
        const running = first === 'pin' ? pinView(list, target, 'header') : unpinView(list, target, 'header')
        await Promise.resolve()
        const queued = first === 'pin' ? unpinView(list, target, 'header') : pinView(list, target, 'header')
        const assertions = Promise.all([
            expect(running).rejects.toMatchObject({ name: 'AbortError' }),
            expect(queued).rejects.toMatchObject({ name: 'AbortError' }),
        ])
        current = false
        client.clear()
        finish()
        await assertions

        expect(createShortcut).toHaveBeenCalledTimes(first === 'pin' ? 1 : 0)
        expect(deleteShortcut).toHaveBeenCalledTimes(first === 'unpin' ? 1 : 0)
        expect(client.getQueryData(listKey)).toBeUndefined()
    })
})
