import type { QueryKey } from '@tanstack/react-query'

import type { StringStorage } from '@/lib/secureStorage'

export const READ_CACHE_TTL_MS = 24 * 60 * 60_000
export const READ_CACHE_ENTRY_LIMIT = 24
export const READ_CACHE_PROJECT_LIMIT = 8
export const READ_CACHE_ENTRY_BYTES = 32 * 1024
export const READ_CACHE_BYTES = 128 * 1024

export interface ReadCacheScope {
    account: string
    host: string
    projectId: number
}

export interface ReadCacheEntry {
    key: QueryKey
    updatedAt: number
    data: unknown
}

export function cacheKey(scope: ReadCacheScope): string {
    return `${scope.account}.${scope.projectId}`
}

export function boundedEntries(entries: readonly ReadCacheEntry[], now = Date.now()): ReadCacheEntry[] {
    let bytes = 2
    const saved: ReadCacheEntry[] = []
    for (const entry of [...entries].sort((a, b) => b.updatedAt - a.updatedAt)) {
        if (!Number.isFinite(entry.updatedAt) || entry.updatedAt > now || now - entry.updatedAt >= READ_CACHE_TTL_MS)
            continue
        const size = Array.from(JSON.stringify(entry)).reduce(
            (total, character) => {
                const code = character.codePointAt(0) ?? 0
                return total + (code < 128 ? 1 : code < 2048 ? 2 : code < 65536 ? 3 : 4)
            },
            saved.length ? 1 : 0
        )
        if (size > READ_CACHE_ENTRY_BYTES || bytes + size > READ_CACHE_BYTES || saved.length >= READ_CACHE_ENTRY_LIMIT)
            continue
        bytes += size
        saved.push(entry)
    }
    return saved
}

export class ReadCacheStore {
    private writes: Promise<unknown> = Promise.resolve()
    private generation = 0

    constructor(private readonly storage: StringStorage) {}

    private enqueue<T>(work: () => Promise<T>): Promise<T> {
        const result = this.writes.then(work)
        this.writes = result.catch(() => undefined)
        return result
    }

    load(scope: ReadCacheScope): Promise<ReadCacheEntry[]> {
        return this.enqueue(async () => {
            const raw = await this.storage.getItem(cacheKey(scope))
            if (!raw) return []
            try {
                const value: unknown = JSON.parse(raw)
                if (!Array.isArray(value)) return []
                return boundedEntries(
                    value.filter(
                        (entry): entry is ReadCacheEntry =>
                            !!entry &&
                            typeof entry === 'object' &&
                            Array.isArray(entry.key) &&
                            typeof entry.updatedAt === 'number' &&
                            entry.key[1] === scope.host &&
                            entry.key[2] === scope.projectId
                    )
                )
            } catch {
                return []
            }
        })
    }

    save(scope: ReadCacheScope, entries: () => ReadCacheEntry[], current: () => boolean): Promise<void> {
        const generation = this.generation
        return this.enqueue(async () => {
            if (generation !== this.generation || !current()) return
            const index = `${scope.account}.scopes`
            const raw = await this.storage.getItem(index)
            const parsed: unknown = raw ? JSON.parse(raw) : []
            const scopes = Array.isArray(parsed)
                ? parsed.filter(
                      (key): key is string =>
                          typeof key === 'string' && key.startsWith(`${scope.account}.`) && key !== index
                  )
                : []
            const key = cacheKey(scope)
            const order = [...scopes.filter((saved) => saved !== key), key]
            await this.storage.setItem(index, JSON.stringify(order))
            await Promise.all(order.slice(0, -READ_CACHE_PROJECT_LIMIT).map((stale) => this.storage.removeItem(stale)))
            if (order.length > READ_CACHE_PROJECT_LIMIT)
                await this.storage.setItem(index, JSON.stringify(order.slice(-READ_CACHE_PROJECT_LIMIT)))
            if (generation !== this.generation || !current()) return
            await this.storage.setItem(key, JSON.stringify(boundedEntries(entries())))
        })
    }

    clearAccount(account: string): Promise<void> {
        this.generation++
        return this.enqueue(async () => {
            const index = `${account}.scopes`
            const raw = await this.storage.getItem(index)
            const parsed: unknown = raw ? JSON.parse(raw) : []
            const keys = Array.isArray(parsed)
                ? parsed.filter(
                      (key): key is string => typeof key === 'string' && key.startsWith(`${account}.`) && key !== index
                  )
                : []
            await Promise.all(keys.map((key) => this.storage.removeItem(key)))
            await this.storage.removeItem(index)
        })
    }

    settled(): Promise<unknown> {
        return this.writes
    }
}
