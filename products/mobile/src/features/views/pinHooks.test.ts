import { QueryClient } from '@tanstack/react-query'

import type { PaginatedApi } from '@/api/reports'
import { createShortcut, deleteShortcut, type FileSystemShortcutApi } from '@/api/shortcuts'

import { pinView, unpinView } from './pinHooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/api/shortcuts', () => ({
    ...jest.requireActual<typeof import('@/api/shortcuts')>('@/api/shortcuts'),
    createShortcut: jest.fn(),
    deleteShortcut: jest.fn(),
}))

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
        const list = { client, listKey, demo: false }
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
})
