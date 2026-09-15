import { v7 as uuidv7 } from 'uuid'

import type { ScopedCache } from '@/lib/cache/ScopedCache'
import type { PrefixedString } from '@/lib/types'
import type { State } from '@/tools/types'

export class SessionManager {
    private cache: ScopedCache<State>
    private mintedUuids = new Map<string, string>()

    constructor(cache: ScopedCache<State>) {
        this.cache = cache
    }

    _getKey(sessionId: string): PrefixedString<'session'> {
        return `session:${sessionId}`
    }

    async getSessionUuid(sessionId: string): Promise<string> {
        const key = this._getKey(sessionId)
        const existingSession = await this.cache.get(key)

        if (existingSession?.uuid) {
            return existingSession.uuid
        }

        // Losing this write costs session continuity in the analytics, not the request, so a
        // tool error still reaches the agent. The uuid is held so every event of this request
        // reports one session even while the write keeps failing.
        const mintedUuid = this.mintedUuids.get(sessionId) ?? uuidv7()
        this.mintedUuids.set(sessionId, mintedUuid)
        await this.cache.warm(key, { uuid: mintedUuid })

        return mintedUuid
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
