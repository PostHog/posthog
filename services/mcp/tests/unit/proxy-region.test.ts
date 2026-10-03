import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
    ApiClient: class {
        users(): { me: () => Promise<{ success: false; error: Error }> } {
            return { me: async () => ({ success: false, error: new Error('INVALID_API_KEY') }) }
        }
    },
}))

import { resolveProxyRegion } from '@/proxy'

describe('resolveProxyRegion', () => {
    const emptyKv = {
        get: async () => null,
        put: async () => undefined,
    } as unknown as KVNamespace

    beforeEach(() => {
        vi.spyOn(console, 'info').mockImplementation(() => undefined)
    })

    it.each([
        { label: 'the region the client asked for', requested: 'eu', expected: 'eu' },
        { label: 'us when the client asked for us', requested: 'us', expected: 'us' },
        { label: 'us when the client asked for nothing', requested: undefined, expected: 'us' },
        { label: 'us when the client asked for a region that does not exist', requested: 'mars', expected: 'us' },
    ])('falls back to $label', async ({ requested, expected }) => {
        await expect(resolveProxyRegion('phx_rejected', 'user-hash', emptyKv, requested)).resolves.toBe(expected)
    })
})
