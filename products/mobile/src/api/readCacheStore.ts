import type { QueryKey } from '@tanstack/react-query'
import { asRecord } from '@/lib/records'
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
        if (saved.length >= READ_CACHE_ENTRY_LIMIT) break
        if (!Number.isFinite(entry.updatedAt) || entry.updatedAt > now || now - entry.updatedAt >= READ_CACHE_TTL_MS)
            continue
        const size = Array.from(JSON.stringify(entry)).reduce(
            (total, character) => {
                const code = character.codePointAt(0) ?? 0
                return total + (code < 128 ? 1 : code < 2048 ? 2 : code < 65536 ? 3 : 4)
            },
            saved.length ? 1 : 0
        )
        if (size > READ_CACHE_ENTRY_BYTES || bytes + size > READ_CACHE_BYTES) continue
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

    private async bundle(scope: ReadCacheScope): Promise<{ slots: number[]; entries: (ReadCacheEntry | null)[] }> {
        const key = cacheKey(scope)
        const raw = await this.storage.getItem(key)
        let value: unknown
        try {
            value = raw ? JSON.parse(raw) : []
        } catch {
            value = []
        }
        const slots =
            value && typeof value === 'object' && 'slots' in value && Array.isArray(value.slots)
                ? value.slots.filter(
                      (slot): slot is number => Number.isInteger(slot) && slot >= 0 && slot < READ_CACHE_ENTRY_LIMIT
                  )
                : []
        const entries: unknown[] = Array.isArray(value)
            ? value
            : await Promise.all(
                  slots.map(async (slot) => {
                      const entry = await this.storage.getItem(`${key}.entry.${slot}`)
                      try {
                          return entry ? JSON.parse(entry) : null
                      } catch {
                          return null
                      }
                  })
              )
        return {
            slots,
            entries: entries.map((entry): ReadCacheEntry | null => {
                const record = asRecord(entry)
                return record &&
                    Array.isArray(record.key) &&
                    typeof record.updatedAt === 'number' &&
                    record.key[1] === scope.host &&
                    record.key[2] === scope.projectId
                    ? { key: record.key, updatedAt: record.updatedAt, data: record.data }
                    : null
            }),
        }
    }

    private async read(scope: ReadCacheScope): Promise<ReadCacheEntry[]> {
        return boundedEntries(
            (await this.bundle(scope)).entries.filter((entry): entry is ReadCacheEntry => entry !== null)
        )
    }

    private async remove(key: string): Promise<void> {
        const raw = await this.storage.getItem(key)
        let value: unknown
        try {
            value = raw ? JSON.parse(raw) : null
        } catch {
            value = null
        }
        if (value && typeof value === 'object' && 'slots' in value && Array.isArray(value.slots)) {
            await Promise.all(
                value.slots
                    .filter(
                        (slot): slot is number => Number.isInteger(slot) && slot >= 0 && slot < READ_CACHE_ENTRY_LIMIT
                    )
                    .map((slot) => this.storage.removeItem(`${key}.entry.${slot}`))
            )
        }
        await this.storage.removeItem(key)
    }

    private serialize(entry: ReadCacheEntry | null): string {
        return JSON.stringify(entry && { key: entry.key, updatedAt: entry.updatedAt, data: entry.data })
    }

    private async write(scope: ReadCacheScope, entries: ReadCacheEntry[]): Promise<void> {
        const key = cacheKey(scope)
        const previous = await this.bundle(scope)
        const remaining = new Set(previous.slots)
        const contents = new Map(previous.entries.map((entry, index) => [this.serialize(entry), previous.slots[index]]))
        const slots = entries.map((entry) => {
            const slot = contents.get(this.serialize(entry))
            if (slot !== undefined) remaining.delete(slot)
            return slot
        })
        for (const [index, entry] of entries.entries()) {
            if (slots[index] !== undefined) continue
            const slot = Array.from({ length: READ_CACHE_ENTRY_LIMIT }, (_, candidate) => candidate).find(
                (candidate) => !slots.includes(candidate)
            )
            if (slot === undefined) continue
            slots[index] = slot
            remaining.delete(slot)
            await this.storage.setItem(`${key}.entry.${slot}`, this.serialize(entry))
        }
        const manifest = JSON.stringify({ slots })
        if (manifest !== JSON.stringify({ slots: previous.slots }) || !previous.slots.length) {
            await this.storage.setItem(key, manifest)
        }
        await Promise.all([...remaining].map((slot) => this.storage.removeItem(`${key}.entry.${slot}`)))
    }

    load(scope: ReadCacheScope): Promise<ReadCacheEntry[]> {
        return this.enqueue(() => this.read(scope))
    }

    evict(scope: ReadCacheScope, rejected: (entry: ReadCacheEntry) => boolean): Promise<void> {
        const generation = this.generation
        return this.enqueue(async () => {
            if (generation !== this.generation) return
            const remaining = (await this.read(scope)).filter((entry) => !rejected(entry))
            if (generation !== this.generation) return
            if (remaining.length) await this.write(scope, remaining)
            else await this.remove(cacheKey(scope))
        })
    }

    evictAccountViews(account: string, host: string): Promise<void> {
        const generation = this.generation
        return this.enqueue(async () => {
            const raw = await this.storage.getItem(`${account}.scopes`)
            const keys: unknown = raw ? JSON.parse(raw) : []
            if (!Array.isArray(keys)) return
            for (const key of keys) {
                if (generation !== this.generation) return
                if (typeof key !== 'string' || !key.startsWith(`${account}.`)) continue
                const projectId = Number(key.slice(account.length + 1))
                if (!Number.isSafeInteger(projectId) || projectId <= 0) continue
                const scope = { account, host, projectId }
                const remaining = (await this.read(scope)).filter((entry) => entry.key[0] !== 'views')
                if (generation !== this.generation) return
                if (remaining.length) await this.write(scope, remaining)
                else await this.remove(key)
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
            if (JSON.stringify(order) !== raw) await this.storage.setItem(index, JSON.stringify(order))
            await Promise.all(order.slice(0, -READ_CACHE_PROJECT_LIMIT).map((stale) => this.remove(stale)))
            if (order.length > READ_CACHE_PROJECT_LIMIT)
                await this.storage.setItem(index, JSON.stringify(order.slice(-READ_CACHE_PROJECT_LIMIT)))
            if (generation !== this.generation || !current()) return
            await this.write(scope, boundedEntries(entries()))
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
            await Promise.all(keys.map((key) => this.remove(key)))
            await this.storage.removeItem(index)
        })
    }

    settled(): Promise<unknown> {
        return this.writes
    }
}
