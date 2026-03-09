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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyFn = (...args: any[]) => any

export function mockKVGet(kv: KVNamespace, impl: AnyFn): void {
    vi.mocked(kv.get as AnyFn).mockImplementation(impl)
}

export function mockKVGetValue(kv: KVNamespace, value: unknown): void {
    vi.mocked(kv.get as AnyFn).mockResolvedValue(value)
}
