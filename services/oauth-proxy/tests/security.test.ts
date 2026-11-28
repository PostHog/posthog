import { afterEach, describe, expect, it, vi } from 'vitest'

import { handleAuthorize } from '@/handlers/authorize'
import worker from '@/index'
import { putClientMapping } from '@/lib/kv'

import { createInMemoryKV } from './helpers'

afterEach(() => {
    vi.unstubAllGlobals()
})

async function storeClient(kv: KVNamespace, proxyClientId: string, redirectUri: string): Promise<void> {
    await putClientMapping(kv, proxyClientId, {
        us_client_id: `${proxyClientId}_us`,
        eu_client_id: `${proxyClientId}_eu`,
        redirect_uris: [redirectUri],
        created_at: Date.now(),
    })
}

async function startFlow(kv: KVNamespace, proxyClientId: string, redirectUri: string, state: string): Promise<URL> {
    const request = new Request(
        `https://oauth.posthog.com/oauth/authorize/?client_id=${proxyClientId}&redirect_uri=${redirectUri}&response_type=code&state=${state}&_region=us`
    )
    const response = await handleAuthorize(request, kv)
    return new URL(response.headers.get('location')!)
}

function regionalCallback(regionalAuthorize: URL, code: string): Request {
    return new Request(
        `${regionalAuthorize.searchParams.get('redirect_uri')}?code=${code}&state=${regionalAuthorize.searchParams.get('state')}`
    )
}

describe('callback client binding', () => {
    it("does not let a second client's flow steal the first client's authorization code", async () => {
        const kv = createInMemoryKV()
        await storeClient(kv, 'clientA', 'https://a.example/cb')
        await storeClient(kv, 'clientB', 'https://b.example/cb')

        const regionalA = await startFlow(kv, 'clientA', 'https://a.example/cb', 'shared')
        await startFlow(kv, 'clientB', 'https://b.example/cb', 'shared')
        const response = await worker.fetch(regionalCallback(regionalA, 'victim_auth_code'), { AUTH_KV: kv })

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('https://a.example/cb')
        expect(location.searchParams.get('code')).toBe('victim_auth_code')
        expect(location.searchParams.get('state')).toBe('shared')
    })

    it.each([
        ["the other client's callback path", 'https://oauth.posthog.com/oauth/callback/clientB_us/', 400],
        ['the shared callback path', 'https://oauth.posthog.com/oauth/callback/', 404],
    ])(
        "refuses a code issued to another client against a flow's nonce on %s",
        async (_name, callbackUrl, expectedStatus) => {
            const kv = createInMemoryKV()
            await storeClient(kv, 'clientA', 'https://a.example/cb')
            await storeClient(kv, 'clientB', 'https://b.example/cb')

            const regionalA = await startFlow(kv, 'clientA', 'https://a.example/cb', 'a_state')
            const callbackRequest = new Request(
                `${callbackUrl}?code=code_for_client_b&state=${regionalA.searchParams.get('state')}`
            )
            const response = await worker.fetch(callbackRequest, { AUTH_KV: kv })

            expect(response.status).toBe(expectedStatus)
            expect(response.headers.get('location')).toBeNull()
        }
    )

    it('completes the flow for a client registered through the proxy', async () => {
        const kv = createInMemoryKV()
        vi.stubGlobal(
            'fetch',
            vi.fn(async (url: string) => {
                const region = new URL(url).hostname.split('.')[0]
                return new Response(JSON.stringify({ client_id: `clientC_${region}` }), {
                    status: 201,
                    headers: { 'Content-Type': 'application/json' },
                })
            })
        )
        await worker.fetch(
            new Request('https://oauth.posthog.com/oauth/register/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ client_name: 'C', redirect_uris: ['https://c.example/cb'] }),
            }),
            { AUTH_KV: kv }
        )

        const regional = await startFlow(kv, 'clientC_us', 'https://c.example/cb', 'c_state')
        const response = await worker.fetch(regionalCallback(regional, 'code_for_c'), { AUTH_KV: kv })

        expect(regional.searchParams.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/clientC_us/')
        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('https://c.example/cb')
        expect(location.searchParams.get('code')).toBe('code_for_c')
        expect(location.searchParams.get('state')).toBe('c_state')
    })
})
