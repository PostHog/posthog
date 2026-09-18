import { vi } from 'vitest'

export function createMockKV(): KVNamespace {
    return {
        get: vi.fn(),
        put: vi.fn(),
        delete: vi.fn(),
        list: vi.fn(),
        getWithMetadata: vi.fn(),
    } as unknown as KVNamespace
}

export function createInMemoryKV(): KVNamespace {
    const store = new Map<string, string>()
    return {
        get: vi.fn((key: string, options?: unknown) => {
            const value = store.get(key)
            if (value === undefined) {
                return Promise.resolve(null)
            }
            return Promise.resolve(options === 'json' ? JSON.parse(value) : value)
        }),
        put: vi.fn((key: string, value: string) => {
            store.set(key, value)
            return Promise.resolve(undefined)
        }),
        delete: vi.fn((key: string) => {
            store.delete(key)
            return Promise.resolve(undefined)
        }),
        list: vi.fn(),
        getWithMetadata: vi.fn(),
    } as unknown as KVNamespace
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyFn = (...args: any[]) => any

export function mockKVGet(kv: KVNamespace, impl: AnyFn): void {
    vi.mocked(kv.get as AnyFn).mockImplementation(impl)
}

export function mockKVGetValue(kv: KVNamespace, value: unknown): void {
    vi.mocked(kv.get as AnyFn).mockResolvedValue(value)
}
