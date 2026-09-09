import { describe, expect, it } from 'vitest'

import { handleAuthorize } from '@/handlers/authorize'
import { handleCallback } from '@/handlers/callback'
import { putClientMapping } from '@/lib/kv'

import { createInMemoryKV } from './helpers'

describe('cross-client state collision', () => {
    it("does not let a second client's flow steal the first client's authorization code", async () => {
        const kv = createInMemoryKV()

        await putClientMapping(kv, 'clientA', {
            us_client_id: 'clientA_us',
            eu_client_id: 'clientA_eu',
            redirect_uris: ['https://a.example/cb'],
            created_at: Date.now(),
        })
        await putClientMapping(kv, 'clientB', {
            us_client_id: 'clientB_us',
            eu_client_id: 'clientB_eu',
            redirect_uris: ['https://b.example/cb'],
            created_at: Date.now(),
        })

        // Flow A: the victim authorizes with client A, using state "shared".
        const requestA = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=clientA&redirect_uri=https://a.example/cb&response_type=code&state=shared&_region=us'
        )
        const responseA = await handleAuthorize(requestA, kv)
        const locationA = new URL(responseA.headers.get('location')!)
        const stateSentForA = locationA.searchParams.get('state')!

        // Flow B: an attacker registers client B and authorizes with the same state value.
        const requestB = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=clientB&redirect_uri=https://b.example/cb&response_type=code&state=shared&_region=us'
        )
        await handleAuthorize(requestB, kv)

        // The regional server calls back with the state value the proxy sent for flow A.
        const callbackRequest = new Request(
            `https://oauth.posthog.com/oauth/callback/?code=victim_auth_code&state=${stateSentForA}`
        )
        const callbackResponse = await handleCallback(callbackRequest, kv)

        expect(callbackResponse.status).toBe(302)
        const location = new URL(callbackResponse.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('https://a.example/cb')
        expect(location.searchParams.get('code')).toBe('victim_auth_code')
        expect(location.searchParams.get('state')).toBe('shared')
    })
})
