import { SessionManager } from '@/lib/utils/SessionManager'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import type { State } from '@/tools'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('uuid', () => ({
    v7: vi.fn(() => 'test-uuid-12345'),
}))

describe('SessionManager', () => {
    let mockCache: ScopedCache<State>
    let sessionManager: SessionManager

    beforeEach(() => {
        mockCache = {
            get: vi.fn(),
            set: vi.fn(),
            delete: vi.fn(),
            clear: vi.fn(),
            has: vi.fn(),
            values: vi.fn(),
            entries: vi.fn(),
            keys: vi.fn(),
        } as unknown as ScopedCache<State>

        sessionManager = new SessionManager(mockCache)
        vi.clearAllMocks()
    })

    describe('getSessionUuid', () => {
        it('should return existing session uuid if it exists', async () => {
            const sessionId = 'test-session-123'
            const existingUuid = 'existing-uuid-456'

            ;(mockCache.get as any).mockResolvedValue({ uuid: existingUuid })

            const result = await sessionManager.getSessionUuid(sessionId)

            expect(result).toBe(existingUuid)
            expect(mockCache.get).toHaveBeenCalledWith('session:test-session-123')
            expect(mockCache.set).not.toHaveBeenCalled()
        })

        it('should create and return new session uuid if none exists', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue(null)

            const result = await sessionManager.getSessionUuid(sessionId)

            expect(result).toBe('test-uuid-12345')
            expect(mockCache.get).toHaveBeenCalledWith('session:test-session-123')
            expect(mockCache.set).toHaveBeenCalledWith('session:test-session-123', {
                uuid: 'test-uuid-12345',
            })
        })

        it('should create new uuid if session exists but has no uuid', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue({})

            const result = await sessionManager.getSessionUuid(sessionId)

            expect(result).toBe('test-uuid-12345')
            expect(mockCache.set).toHaveBeenCalledWith('session:test-session-123', {
                uuid: 'test-uuid-12345',
            })
        })
    })

    describe('hasSession', () => {
        it('should return true if session exists with uuid', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue({ uuid: 'some-uuid' })

            const result = await sessionManager.hasSession(sessionId)

            expect(result).toBe(true)
            expect(mockCache.get).toHaveBeenCalledWith('session:test-session-123')
        })

        it('should return false if session does not exist', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue(null)

            const result = await sessionManager.hasSession(sessionId)

            expect(result).toBe(false)
            expect(mockCache.get).toHaveBeenCalledWith('session:test-session-123')
        })

        it('should return false if session exists but has no uuid', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue({})

            const result = await sessionManager.hasSession(sessionId)

            expect(result).toBe(false)
        })

        it('should return false if session exists with undefined uuid', async () => {
            const sessionId = 'test-session-123'

            ;(mockCache.get as any).mockResolvedValue({ uuid: undefined })

            const result = await sessionManager.hasSession(sessionId)

            expect(result).toBe(false)
        })
    })

    describe('removeSession', () => {
        it('should delete session from cache', async () => {
            const sessionId = 'test-session-123'

            await sessionManager.removeSession(sessionId)

            expect(mockCache.delete).toHaveBeenCalledWith('session:test-session-123')
        })

        it('should handle removal of non-existent session gracefully', async () => {
            const sessionId = 'non-existent-session'

            ;(mockCache.delete as any).mockResolvedValue(undefined)

            await sessionManager.removeSession(sessionId)

            expect(mockCache.delete).toHaveBeenCalledWith('session:non-existent-session')
        })
    })

    describe('clearAllSessions', () => {
        it('should clear all sessions from cache', async () => {
            await sessionManager.clearAllSessions()

            expect(mockCache.clear).toHaveBeenCalled()
        })
    })

    describe('_getKey', () => {
        it('should format session key correctly', async () => {
            const sessionId = 'test-session'

            const key = await sessionManager._getKey(sessionId)

            expect(key).toBe('session:test-session')
        })

        it('should handle special characters in session id', async () => {
            const sessionId = 'test-session!@#$%^&*()'

            const key = await sessionManager._getKey(sessionId)

            expect(key).toBe('session:test-session!@#$%^&*()')
        })

        it('should handle empty session id', async () => {
            const sessionId = ''

            const key = await sessionManager._getKey(sessionId)

            expect(key).toBe('session:')
        })
    })

    describe('integration scenarios', () => {
        it('should handle multiple sequential operations', async () => {
            const sessionId = 'test-session'

            ;(mockCache.get as any).mockResolvedValueOnce(null)
            ;(mockCache.get as any).mockResolvedValueOnce({ uuid: 'test-uuid-12345' })
            ;(mockCache.get as any).mockResolvedValueOnce(null)

            const uuid1 = await sessionManager.getSessionUuid(sessionId)
            expect(uuid1).toBe('test-uuid-12345')
            expect(mockCache.set).toHaveBeenCalled()

            const hasSession = await sessionManager.hasSession(sessionId)
            expect(hasSession).toBe(true)

            await sessionManager.removeSession(sessionId)
            expect(mockCache.delete).toHaveBeenCalled()

            const hasSessionAfterRemove = await sessionManager.hasSession(sessionId)
            expect(hasSessionAfterRemove).toBe(false)
        })

        it('should handle concurrent sessions', async () => {
            const sessionId1 = 'session-1'
            const sessionId2 = 'session-2'

            ;(mockCache.get as any).mockImplementation((key: string) => {
                if (key === 'session:session-1') {
                    return Promise.resolve({ uuid: 'uuid-1' })
                }
                if (key === 'session:session-2') {
                    return Promise.resolve({ uuid: 'uuid-2' })
                }
                return Promise.resolve(null)
            })

            const [uuid1, uuid2] = await Promise.all([
                sessionManager.getSessionUuid(sessionId1),
                sessionManager.getSessionUuid(sessionId2),
            ])

            expect(uuid1).toBe('uuid-1')
            expect(uuid2).toBe('uuid-2')
        })
    })
})
