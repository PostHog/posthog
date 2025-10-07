import { ScopedCache } from '@/lib/utils/cache/ScopedCache'

interface DurableObjectStorage {
    get<T = unknown>(key: string): Promise<T | undefined>
    put<T>(key: string, value: T): Promise<void>
    delete(key: string): Promise<boolean>
    delete(keys: string[]): Promise<number>
    list(options?: {
        prefix?: string
        start?: string
        end?: string
        limit?: number
        reverse?: boolean
    }): Promise<Map<string, unknown>>
}

export class DurableObjectCache<T extends Record<string, any>> extends ScopedCache<T> {
    private storage: DurableObjectStorage
    private userHash: string

    constructor(scope: string, storage: DurableObjectStorage) {
        super(scope)
        this.userHash = scope
        this.storage = storage
    }

    private getScopedKey(key: string): string {
        return `user:${this.userHash}:${key}`
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        const scopedKey = this.getScopedKey(key as string)
        return await this.storage.get(scopedKey)
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.storage.put(scopedKey, value)
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.storage.delete(scopedKey)
    }

    async clear(): Promise<void> {
        const prefix = `user:${this.userHash}:`
        const keys = await this.storage.list({ prefix })
        const keysArray = Array.from(keys.keys())
        await this.storage.delete(keysArray)
    }
}
