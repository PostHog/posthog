const mockAuth = { signedIn: true, host: 'https://example.com', user: { uuid: 'user-1' }, projectId: 1 }
const mockSecure = new Map<string, string>()
let mockFailedRead: string | undefined
let mockRevision = 0

jest.mock('@/auth/tokens', () => ({ getSessionTokens: () => ({ accessToken: 'fake' }) }))

jest.mock('@/auth/authStore', () => ({
    useAuthStore: { getState: () => mockAuth },
    addSessionEndTask: jest.fn(),
}))
jest.mock('expo-crypto', () => ({
    CryptoDigestAlgorithm: { SHA256: 'sha256' },
    digestStringAsync: async (_algorithm: string, value: string) => Buffer.from(value).toString('hex'),
    randomUUID: () => `revision-${mockRevision++}`,
}))
jest.mock('expo-secure-store', () => ({
    getItemAsync: async (key: string) => {
        if (key === mockFailedRead) {
            mockFailedRead = undefined
            throw new Error('SecureStore read failed')
        }
        return mockSecure.get(key) ?? null
    },
    setItemAsync: async (key: string, value: string) => {
        if (Buffer.byteLength(value, 'utf8') > 2048) {
            throw new Error('SecureStore item too large')
        }
        mockSecure.set(key, value)
    },
    deleteItemAsync: async (key: string) => {
        mockSecure.delete(key)
    },
}))

import { chatDrafts, draftIdentity, draftScope } from './draftPersistence'
import { EMPTY_QUEUE, queueActions, queueReducer } from './messageQueue'

beforeEach(async () => {
    await chatDrafts.clear([])
    mockSecure.clear()
    mockFailedRead = undefined
    mockAuth.projectId = 1
})

describe('chat draft persistence', () => {
    it('stores long non-ASCII drafts in SecureStore without splitting surrogate pairs', async () => {
        const identity = draftIdentity() as string
        const scope = (await draftScope(identity)) as string
        const text = `${'a'.repeat(493)}${'🦔'.repeat(2500)}\n${'漢'.repeat(2100)}`
        await chatDrafts.save(scope, 'new-chat', { text, reportIds: [] })
        expect(await chatDrafts.load(scope, 'new-chat')).toEqual({ text, reportIds: [] })
        expect(mockSecure.size).toBeGreaterThan(3)
        for (const value of mockSecure.values()) {
            expect(Buffer.byteLength(value, 'utf8')).toBeLessThanOrEqual(2048)
            expect(value).not.toMatch(/[\uD800-\uDBFF]$|^[\uDC00-\uDFFF]/)
        }
    })

    it('preserves all saved queues when a project manifest read fails', async () => {
        const scope = (await draftScope(draftIdentity() as string)) as string
        const first = queueReducer(EMPTY_QUEUE, queueActions.enqueue('First saved question'))
        const second = queueReducer(EMPTY_QUEUE, queueActions.enqueue('Second saved question'))
        await chatDrafts.saveQueue(scope, 'task:first', first)
        const before = new Map(mockSecure)
        mockFailedRead = scope
        await expect(chatDrafts.saveQueue(scope, 'task:second', second)).rejects.toThrow('SecureStore read failed')
        expect(mockSecure).toEqual(before)
        expect((await chatDrafts.loadQueue(scope, 'task:first')).rows).toMatchObject([{ text: 'First saved question' }])
        await chatDrafts.saveQueue(scope, 'task:second', second)
        expect((await chatDrafts.loadQueue(scope, 'task:first')).rows).toHaveLength(1)
        expect((await chatDrafts.loadQueue(scope, 'task:second')).rows).toHaveLength(1)
    })

    it('wipes encrypted drafts for every project on session end and invalidates pending sends', async () => {
        const first = (await draftScope(draftIdentity() as string)) as string
        const settle = await chatDrafts.beginSend(first, 'new-chat', { text: 'Private', reportIds: [] })
        mockAuth.projectId = 2
        const second = (await draftScope(draftIdentity() as string)) as string
        await chatDrafts.save(second, 'task:1', { text: 'Other project', reportIds: [] })
        const auth = jest.requireMock<{ addSessionEndTask: jest.Mock }>('@/auth/authStore')
        await Promise.all(auth.addSessionEndTask.mock.calls.map(([task]) => task()))
        await settle(false)
        expect(mockSecure.size).toBe(0)
        expect(await chatDrafts.load(first, 'new-chat')).toBeNull()
        expect(await chatDrafts.load(second, 'task:1')).toBeNull()
    })
})
