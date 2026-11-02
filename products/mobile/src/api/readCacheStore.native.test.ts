import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'
import { secureStorage } from '@/lib/secureStorage'
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
    afterEach(() => jest.restoreAllMocks())

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
