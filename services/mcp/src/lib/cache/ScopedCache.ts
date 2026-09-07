import { isTransientRedisError } from './redis-errors'

export abstract class ScopedCache<T extends Record<string, any>> {
    constructor(protected scope: string) {}

    abstract get<K extends keyof T>(key: K): Promise<T[K] | undefined>
    abstract set<K extends keyof T>(key: K, value: T[K]): Promise<void>
    abstract delete<K extends keyof T>(key: K): Promise<void>
    abstract clear(): Promise<void>

    async setMany(entries: Partial<{ [K in keyof T]: T[K] }>): Promise<void> {
        const promises: Promise<void>[] = []
        for (const key of Object.keys(entries) as (keyof T)[]) {
            const value = entries[key]
            if (value !== undefined) {
                promises.push(this.set(key, value as T[typeof key]))
            }
        }
        await Promise.all(promises)
    }

    /**
     * Write a value the caller can afford to lose. A transient cache outage then
     * costs a refetch on the next request instead of failing this one. A write a
     * person is told about must keep using `set` so the report stays true, as in
     * `switch-project` reporting the new active project.
     */
    async warm<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        try {
            await this.set(key, value)
        } catch (error) {
            if (!isTransientRedisError(error)) {
                throw error
            }
            console.warn(`[ScopedCache] dropped warm write of ${String(key)}:`, error)
        }
    }

    async warmMany(entries: Partial<{ [K in keyof T]: T[K] }>): Promise<void> {
        const promises: Promise<void>[] = []
        for (const key of Object.keys(entries) as (keyof T)[]) {
            const value = entries[key]
            if (value !== undefined) {
                promises.push(this.warm(key, value as T[typeof key]))
            }
        }
        await Promise.all(promises)
    }
}
