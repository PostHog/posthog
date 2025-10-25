import type { PrefixedString } from '@/lib/types'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import type { State } from '@/tools'
import { v7 as uuidv7 } from 'uuid'

export class SessionManager {
    private cache: ScopedCache<State>

    constructor(cache: ScopedCache<State>) {
        this.cache = cache
    }

    async _getKey(sessionId: string): Promise<PrefixedString<'session'>> {
        return `session:${sessionId}`
    }

    async getSessionUuid(sessionId: string): Promise<string> {
        const key = await this._getKey(sessionId)

        const existingSession = await this.cache.get(key)

        if (existingSession?.uuid) {
            return existingSession.uuid
        }

        const newSessionUuid = uuidv7()

        await this.cache.set(key, { uuid: newSessionUuid })

        return newSessionUuid
    }

    async hasSession(sessionId: string): Promise<boolean> {
        const key = await this._getKey(sessionId)

        const session = await this.cache.get(key)
        return !!session?.uuid
    }

    async removeSession(sessionId: string): Promise<void> {
        const key = await this._getKey(sessionId)

        await this.cache.delete(key)
    }

    async clearAllSessions(): Promise<void> {
        await this.cache.clear()
    }
}
