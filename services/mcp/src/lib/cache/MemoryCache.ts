import { ScopedCache } from './ScopedCache'

const _cacheStore = new Map<string, any>()

export class MemoryCache<T extends Record<string, any>> extends ScopedCache<T> {
    private cache: Map<string, any> = new Map()

    constructor(scope: string) {
        super(scope)
        this.cache = _cacheStore.get(scope) || new Map()
        _cacheStore.set(scope, this.cache)
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        return this.cache.get(key as string)
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        this.cache.set(key as string, value)
        return
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        this.cache.delete(key as string)
    }

    async compareAndSet<K extends keyof T>(key: K, expected: T[K] | undefined, value: T[K]): Promise<boolean> {
        if (JSON.stringify(this.cache.get(key as string)) !== JSON.stringify(expected)) {
            return false
        }
        this.cache.set(key as string, value)
        return true
    }

    async clear(): Promise<void> {
        this.cache.clear()
    }
}
