import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RegionService } from '@/server/services/region'
import { createMockCache, createMockConfig } from '../fixtures'

vi.mock('@/api/client', () => ({
    ApiClient: vi.fn().mockImplementation(({ baseUrl }) => ({
        users: () => ({
            me: vi.fn().mockImplementation(async () => {
                if (baseUrl === 'https://us.posthog.com') {
                    return { success: true, data: { distinct_id: 'us-user' } }
                }
                return { success: false }
            }),
        }),
    })),
}))

vi.mock('@/lib/constants', () => ({
    CUSTOM_BASE_URL: undefined,
}))

describe('RegionService', () => {
    let regionService: RegionService

    beforeEach(() => {
        vi.clearAllMocks()
        regionService = new RegionService(createMockConfig())
    })

    describe('detectRegion', () => {
        it('returns "us" when US API succeeds', async () => {
            const { ApiClient } = await import('@/api/client')
            vi.mocked(ApiClient).mockImplementation(({ baseUrl }: { baseUrl: string }) => ({
                users: () => ({
                    me: async () =>
                        baseUrl.includes('us')
                            ? { success: true, data: { distinct_id: 'user' } }
                            : { success: false },
                }),
            }))

            const region = await regionService.detectRegion('phx_test')
            expect(region).toBe('us')
        })

        it('returns "eu" when only EU API succeeds', async () => {
            const { ApiClient } = await import('@/api/client')
            vi.mocked(ApiClient).mockImplementation(({ baseUrl }: { baseUrl: string }) => ({
                users: () => ({
                    me: async () =>
                        baseUrl.includes('eu')
                            ? { success: true, data: { distinct_id: 'user' } }
                            : { success: false },
                }),
            }))

            const region = await regionService.detectRegion('phx_test')
            expect(region).toBe('eu')
        })

        it('returns undefined when neither API succeeds', async () => {
            const { ApiClient } = await import('@/api/client')
            vi.mocked(ApiClient).mockImplementation(() => ({
                users: () => ({
                    me: async () => ({ success: false }),
                }),
            }))

            const region = await regionService.detectRegion('phx_invalid')
            expect(region).toBeUndefined()
        })
    })

    describe('getApiBaseUrl', () => {
        it('returns cached region URL', async () => {
            const cache = createMockCache()
            vi.mocked(cache.get).mockResolvedValue('eu')

            const url = await regionService.getApiBaseUrl('phx_test', cache)

            expect(url).toBe('https://eu.posthog.com')
            expect(cache.get).toHaveBeenCalledWith('region')
        })

        it('detects and caches region when not cached', async () => {
            const { ApiClient } = await import('@/api/client')
            vi.mocked(ApiClient).mockImplementation(({ baseUrl }: { baseUrl: string }) => ({
                users: () => ({
                    me: async () =>
                        baseUrl.includes('us')
                            ? { success: true, data: { distinct_id: 'user' } }
                            : { success: false },
                }),
            }))

            const cache = createMockCache()
            vi.mocked(cache.get).mockResolvedValue(undefined)

            const url = await regionService.getApiBaseUrl('phx_test', cache)

            expect(url).toBe('https://us.posthog.com')
            expect(cache.set).toHaveBeenCalledWith('region', 'us')
        })

        it('uses internal URL when available for US', async () => {
            const config = createMockConfig({ internalApiUrlUs: 'http://internal-us' })
            regionService = new RegionService(config)

            const cache = createMockCache()
            vi.mocked(cache.get).mockResolvedValue('us')

            const url = await regionService.getApiBaseUrl('phx_test', cache)

            expect(url).toBe('http://internal-us')
        })

        it('uses internal URL when available for EU', async () => {
            const config = createMockConfig({ internalApiUrlEu: 'http://internal-eu' })
            regionService = new RegionService(config)

            const cache = createMockCache()
            vi.mocked(cache.get).mockResolvedValue('eu')

            const url = await regionService.getApiBaseUrl('phx_test', cache)

            expect(url).toBe('http://internal-eu')
        })

        it('falls back to public URL when internal URL not configured', async () => {
            const cache = createMockCache()
            vi.mocked(cache.get).mockResolvedValue('us')

            const url = await regionService.getApiBaseUrl('phx_test', cache)

            expect(url).toBe('https://us.posthog.com')
        })
    })
})
