import { QueryClient } from '@tanstack/react-query'
import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'
import { secureStorage } from '@/lib/secureStorage'
import { persistReadCache } from './readCache'
import { ReadCacheStore } from './readCacheStore'

const mockValues = new Map<string, string>()
let mockRevision = 0
jest.mock('expo-crypto', () => ({ randomUUID: () => `revision-${mockRevision++}` }))
jest.mock('expo-secure-store', () => ({
    getItemAsync: jest.fn(async (key: string) => mockValues.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
        mockValues.set(key, value)
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
        mockValues.delete(key)
    }),
}))

describe('encrypted read cache native storage work', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        mockValues.clear()
        jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => mockValues.get(key) ?? null)
        jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => {
            mockValues.set(key, value)
        })
        jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async (key) => {
            mockValues.delete(key)
        })
        jest.replaceProperty(Platform, 'OS', 'android')
    })
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each(['chunk', 'manifest'] as const)(
        'propagates a temporary %s read failure without erasing saved data',
        async (part) => {
            const scope = { account: 'example-account', host: 'https://example.com', projectId: 1 }
            const key = ['views', scope.host, 1, 'web', '-']
            const store = new ReadCacheStore(secureStorage)
            await store.save(
                scope,
                () => [{ key, updatedAt: Date.now(), data: { metrics: [], readAt: Date.now() } }],
                () => true
            )
            const saved = new Map(mockValues)
            const read = jest.mocked(SecureStore.getItemAsync)
            const original = read.getMockImplementation()
            if (!original) throw new Error('Missing native read mock')
            read.mockImplementation(async (name, options) => {
                if (part === 'manifest' ? name === `${scope.account}.1` : /revision-.*\.0$/.test(name))
                    throw new Error('Temporary read failure')
                return original(name, options)
            })
            const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
            const session = persistReadCache(client, store, scope, () => true)
            await session.ready
            await session.flush()
            expect(mockValues).toEqual(saved)
            read.mockImplementation(original)
            await session.flush()
            expect(client.getQueryData(key)).toMatchObject({ metrics: [], restoredFromDevice: true })
            session.stop()
            client.clear()
        }
    )

    test.each(['chunk', 'manifest', 'cleanup', 'remove'] as const)(
        'recovers all chunks after interruption during %s',
        async (stage) => {
            const key = 'example-value'
            const oldValue = 'a'.repeat(1200)
            const nextValue = 'b'.repeat(1200)
            await secureStorage.setItem(key, oldValue)
            const set = jest.mocked(SecureStore.setItemAsync)
            const remove = jest.mocked(SecureStore.deleteItemAsync)
            const read = jest.mocked(SecureStore.getItemAsync)
            const originalSet = set.getMockImplementation()
            const originalRemove = remove.getMockImplementation()
            const originalRead = read.getMockImplementation()
            if (!originalSet || !originalRemove || !originalRead) throw new Error('Missing native storage mock')
            let interrupted = false
            const fail = (): never => {
                interrupted = true
                throw new Error('Storage interrupted')
            }
            read.mockImplementation(async (name, options) => {
                if (interrupted) fail()
                return originalRead(name, options)
            })
            set.mockImplementation(async (name, value, options) => {
                if (interrupted) fail()
                await originalSet(name, value, options)
                if ((stage === 'chunk' && name.endsWith('.0')) || (stage === 'manifest' && name === key)) fail()
            })
            remove.mockImplementation(async (name, options) => {
                if (interrupted) fail()
                if (stage === 'cleanup' && name.endsWith('.0')) fail()
                await originalRemove(name, options)
                if (stage === 'remove' && name === key) fail()
            })
            const work = stage === 'remove' ? secureStorage.removeItem(key) : secureStorage.setItem(key, nextValue)
            await expect(work).rejects.toThrow('Storage interrupted')
            read.mockImplementation(originalRead)
            set.mockImplementation(originalSet)
            remove.mockImplementation(originalRemove)
            const expected = stage === 'remove' ? null : stage === 'chunk' ? oldValue : nextValue
            expect(await secureStorage.getItem(key)).toBe(expected)
            expect(mockValues.has(`${key}.revisions`)).toBe(false)
            const current = JSON.parse(mockValues.get(key) ?? 'null')
            expect([...mockValues.keys()].sort()).toEqual(
                current
                    ? [
                          key,
                          ...Array.from({ length: current.count }, (_, i) => `${key}.${current.revision}.${i}`),
                      ].sort()
                    : []
            )
            await secureStorage.removeItem(key)
            expect(mockValues.size).toBe(0)
        }
    )

    it('limits a full-cache refresh to changed chunks and clears the account on logout', async () => {
        jest.replaceProperty(Platform, 'OS', 'android')
        const scope = { account: 'example-account', host: 'https://example.com', projectId: 1 }
        const store = new ReadCacheStore(secureStorage)
        const entries = Array.from({ length: 24 }, (_, index) => ({
            key: ['views', scope.host, 1, 'insight', String(index), '-', '-'],
            updatedAt: Date.now(),
            data: { series: 'x'.repeat(5000), value: 42 },
        }))
        await store.save(
            scope,
            () => entries,
            () => true
        )
        jest.mocked(SecureStore.setItemAsync).mockClear()
        jest.mocked(SecureStore.deleteItemAsync).mockClear()
        const first = entries[0]
        if (!first) throw new Error('Missing full-cache fixture')
        entries[0] = { ...first, data: { ...first.data, value: 43 } }
        await store.save(
            scope,
            () => entries,
            () => true
        )
        expect(jest.mocked(SecureStore.setItemAsync).mock.calls.length).toBeLessThan(16)
        expect(jest.mocked(SecureStore.deleteItemAsync).mock.calls.length).toBeLessThan(16)
        expect(await store.load(scope)).toHaveLength(24)
        jest.mocked(SecureStore.setItemAsync).mockClear()
        jest.mocked(SecureStore.deleteItemAsync).mockClear()
        await store.save(
            scope,
            () => entries,
            () => true
        )
        expect(SecureStore.setItemAsync).not.toHaveBeenCalled()
        expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled()
        await store.clearAccount(scope.account)
        expect(mockValues.size).toBe(0)
    })
})
