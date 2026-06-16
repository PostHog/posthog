import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
    getLiveAdvertisedOAuthScopes,
    resetAuthorizationServerScopesCacheForTests,
} from '@/lib/authorization-server-scopes'
import { getAdvertisedOAuthScopes } from '@/tools/toolDefinitions'

const AS_URL = 'https://oauth.posthog.test'

const jsonResponse = (body: unknown): Response => ({ ok: true, json: async () => body }) as unknown as Response

const advertised = getAdvertisedOAuthScopes()
const identityScopes = advertised.filter((scope) => !scope.includes(':'))
const firstResourceScope = advertised.find((scope) => scope.includes(':')) as string

describe('getLiveAdvertisedOAuthScopes', () => {
    beforeEach(() => {
        resetAuthorizationServerScopesCacheForTests()
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('drops a resource scope the live authorization server does not recognise', async () => {
        // Simulate the deploy-skew window: the MCP image advertises a scope the
        // AS doesn't know yet. The AS metadata omits it, so we must not publish it.
        const live = advertised.filter((scope) => scope !== firstResourceScope)
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => jsonResponse({ scopes_supported: live }))
        )

        const result = await getLiveAdvertisedOAuthScopes(AS_URL)

        expect(result).not.toContain(firstResourceScope)
        for (const scope of live) {
            expect(result).toContain(scope)
        }
    })

    it('always keeps identity scopes even when the AS omits them', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => jsonResponse({ scopes_supported: ['dashboard:read'] }))
        )

        const result = await getLiveAdvertisedOAuthScopes(AS_URL)

        const missing = identityScopes.filter((scope) => !result.includes(scope))
        expect(missing).toEqual([])
    })

    it('falls back to the full static list when the fetch rejects', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => {
                throw new Error('network down')
            })
        )

        const result = await getLiveAdvertisedOAuthScopes(AS_URL)

        expect([...result]).toEqual([...advertised])
    })

    it('falls back to the static list on a non-200 response', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => ({ ok: false, json: async () => ({}) }) as unknown as Response)
        )

        const result = await getLiveAdvertisedOAuthScopes(AS_URL)

        expect([...result]).toEqual([...advertised])
    })

    it('falls back to the static list when scopes_supported is empty or malformed', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => jsonResponse({ scopes_supported: [] }))
        )

        const result = await getLiveAdvertisedOAuthScopes(AS_URL)

        expect([...result]).toEqual([...advertised])
    })

    it('caches the live list and does not refetch within the TTL', async () => {
        const fetchMock = vi.fn(async () => jsonResponse({ scopes_supported: advertised }))
        vi.stubGlobal('fetch', fetchMock)

        await getLiveAdvertisedOAuthScopes(AS_URL)
        await getLiveAdvertisedOAuthScopes(AS_URL)

        expect(fetchMock).toHaveBeenCalledTimes(1)
    })
})
