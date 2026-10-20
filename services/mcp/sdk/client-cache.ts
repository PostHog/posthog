import { ScopedCache } from '@/lib/cache/ScopedCache'

/** SDK caches belong to their client instance, including forwarded connection contexts. */
export class MemoryCache<T extends Record<string, unknown>> extends ScopedCache<T> {
    private readonly values = new Map<keyof T, T[keyof T]>()

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        return this.values.get(key) as T[K] | undefined
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        this.values.set(key, value)
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        this.values.delete(key)
    }

    async clear(): Promise<void> {
        this.values.clear()
    }
}
