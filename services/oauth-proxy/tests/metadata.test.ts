import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const AUTHORITATIVE_METADATA = {
    issuer: 'https://us.posthog.com',
    authorization_endpoint: 'https://us.posthog.com/oauth/authorize/',
    token_endpoint: 'https://us.posthog.com/oauth/token/',
    revocation_endpoint: 'https://us.posthog.com/oauth/revoke/',
    introspection_endpoint: 'https://us.posthog.com/oauth/introspect/',
    userinfo_endpoint: 'https://us.posthog.com/oauth/userinfo/',
    jwks_uri: 'https://us.posthog.com/.well-known/jwks.json',
    registration_endpoint: 'https://us.posthog.com/oauth/register/',
    scopes_supported: ['openid', 'profile', 'email'],
    response_types_supported: ['code'],
    response_modes_supported: ['query'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    token_endpoint_auth_methods_supported: ['none', 'client_secret_post'],
    code_challenge_methods_supported: ['S256'],
    service_documentation: 'https://posthog.com/docs/model-context-protocol',
    client_id_metadata_document_supported: true,
}

describe('handleMetadata', () => {
    beforeEach(() => {
        vi.resetModules()
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: true,
                json: () => Promise.resolve(AUTHORITATIVE_METADATA),
            })
        )
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('returns valid OAuth authorization server metadata with endpoints rewritten', async () => {
        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')
        const response = await handleMetadata(request)
        const data = (await response.json()) as Record<string, unknown>

        expect(response.status).toBe(200)
        expect(data.issuer).toBe('https://oauth.posthog.com')
        expect(data.authorization_endpoint).toBe('https://oauth.posthog.com/oauth/authorize/')
        expect(data.token_endpoint).toBe('https://oauth.posthog.com/oauth/token/')
        expect(data.revocation_endpoint).toBe('https://oauth.posthog.com/oauth/revoke/')
        expect(data.introspection_endpoint).toBe('https://oauth.posthog.com/oauth/introspect/')
        expect(data.userinfo_endpoint).toBe('https://oauth.posthog.com/oauth/userinfo/')
        expect(data.jwks_uri).toBe('https://oauth.posthog.com/.well-known/jwks.json')
        expect(data.registration_endpoint).toBe('https://oauth.posthog.com/oauth/register/')
    })

    it('preserves non-endpoint fields from authoritative metadata', async () => {
        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')
        const response = await handleMetadata(request)
        const data = (await response.json()) as Record<string, unknown>

        expect(data.scopes_supported).toEqual(AUTHORITATIVE_METADATA.scopes_supported)
        expect(data.response_types_supported).toEqual(AUTHORITATIVE_METADATA.response_types_supported)
        expect(data.grant_types_supported).toEqual(AUTHORITATIVE_METADATA.grant_types_supported)
        expect(data.code_challenge_methods_supported).toContain('S256')
        expect(data.service_documentation).toBe(AUTHORITATIVE_METADATA.service_documentation)
        expect(data.client_id_metadata_document_supported).toBe(true)
    })

    it('caches the authoritative metadata', async () => {
        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')

        await handleMetadata(request)
        await handleMetadata(request)

        expect(fetch).toHaveBeenCalledTimes(1)
    })

    it('re-fetches after cache expires', async () => {
        vi.useFakeTimers()
        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')

        await handleMetadata(request)
        expect(fetch).toHaveBeenCalledTimes(1)

        // Advance past the 10-minute cache TTL
        vi.advanceTimersByTime(601 * 1000)

        await handleMetadata(request)
        expect(fetch).toHaveBeenCalledTimes(2)

        vi.useRealTimers()
    })

    it('returns 502 when authoritative metadata fetch fails and no cache exists', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: false,
                statusText: 'Internal Server Error',
            })
        )

        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')

        const response = await handleMetadata(request)
        expect(response.status).toBe(502)
        const data = (await response.json()) as Record<string, unknown>
        expect(data.error).toBe('server_error')
    })

    it('returns 502 when metadata refresh fails after cache expires', async () => {
        vi.useFakeTimers()
        const { handleMetadata } = await import('@/handlers/metadata')
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')

        // Populate cache with a successful fetch
        const response1 = await handleMetadata(request)
        expect(response1.status).toBe(200)

        // Expire cache
        vi.advanceTimersByTime(601 * 1000)

        // Make fetch fail
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: false,
                statusText: 'Service Unavailable',
            })
        )

        const response2 = await handleMetadata(request)
        expect(response2.status).toBe(502)
        const data = (await response2.json()) as Record<string, unknown>
        expect(data.error).toBe('server_error')

        vi.useRealTimers()
    })
})
