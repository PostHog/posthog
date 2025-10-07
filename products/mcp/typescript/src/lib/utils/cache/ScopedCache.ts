export abstract class ScopedCache<T extends Record<string, any>> {
    constructor(private scope: string) {}

    abstract get<K extends keyof T>(key: K): Promise<T[K] | undefined>
    abstract set<K extends keyof T>(key: K, value: T[K]): Promise<void>
    abstract delete<K extends keyof T>(key: K): Promise<void>
    abstract clear(): Promise<void>
}
