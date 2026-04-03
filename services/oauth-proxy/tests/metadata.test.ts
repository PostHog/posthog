import { describe, expect, it } from 'vitest'

import { handleMetadata } from '@/handlers/metadata'

describe('handleMetadata', () => {
    it('returns valid OAuth authorization server metadata', async () => {
        const request = new Request('https://oauth.posthog.com/.well-known/oauth-authorization-server')
        const response = handleMetadata(request)
        const data = (await response.json()) as Record<string, unknown>

        expect(response.status).toBe(200)
        expect(data.issuer).toBe('https://oauth.posthog.com')
        expect(data.authorization_endpoint).toBe('https://oauth.posthog.com/oauth/authorize/')
        expect(data.token_endpoint).toBe('https://oauth.posthog.com/oauth/token/')
        expect(data.registration_endpoint).toBe('https://oauth.posthog.com/oauth/register/')
        expect(data.code_challenge_methods_supported).toContain('S256')
    })
})
