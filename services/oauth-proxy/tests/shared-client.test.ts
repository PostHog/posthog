import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { handleAuthorize } from '@/handlers/authorize'
import { handleCallback } from '@/handlers/callback'
import { handleToken } from '@/handlers/token'
import { hashKey, putPendingCallback } from '@/lib/kv'

import { createInMemoryKV } from './helpers'

// One registration used by many users, as an integration that runs DCR once per connector
// (or ships a fixed client) does. Users from both regions share this client_id, so the
// region selection keyed by client_id is last-writer-wins across users.
const PROXY_CLIENT_ID = 'shared_proxy_client'
const CLIENT_REDIRECT_URI = 'https://integration.example.com/oauth/callback'
const MAPPING = {
    us_client_id: PROXY_CLIENT_ID,
    eu_client_id: 'shared_eu_client',
    us_client_secret: 'us_secret',
    eu_client_secret: 'eu_secret',
    redirect_uris: [CLIENT_REDIRECT_URI],
    created_at: 0,
}

type Region = 'us' | 'eu'

function stubRegions(issued: Record<string, Region>): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input instanceof Request ? input.url : input))
        const region: Region = url.hostname.startsWith('eu.') ? 'eu' : 'us'
        const body = new URLSearchParams(String(init?.body ?? (input instanceof Request ? await input.text() : '')))
        const credential = body.get('code') ?? body.get('refresh_token') ?? ''
        const expectedClient = region === 'eu' ? MAPPING.eu_client_id : MAPPING.us_client_id
        if (issued[credential] === region && body.get('client_id') === expectedClient) {
            return new Response(JSON.stringify({ access_token: `pha_${region}_${credential}`, token_type: 'bearer' }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        }
        return new Response(JSON.stringify({ error: 'invalid_grant' }), {
            status: 400,
            headers: { 'Content-Type': 'application/json' },
        })
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
}

interface PendingFlow {
    nonce: string
    callbackUrl: string
}

async function authorize(kv: KVNamespace, region: Region, state: string): Promise<PendingFlow> {
    const response = await handleAuthorize(
        new Request(
            `https://oauth.posthog.com/oauth/authorize/?client_id=${PROXY_CLIENT_ID}` +
                `&redirect_uri=${encodeURIComponent(CLIENT_REDIRECT_URI)}&response_type=code&state=${state}&_region=${region}`
        ),
        kv
    )
    const regionalParams = new URL(response.headers.get('location')!).searchParams
    return { nonce: regionalParams.get('state')!, callbackUrl: regionalParams.get('redirect_uri')! }
}

async function callback(kv: KVNamespace, flow: PendingFlow, query: string): Promise<Response> {
    return handleCallback(new Request(`${flow.callbackUrl}?${query}&state=${flow.nonce}`), kv)
}

async function token(kv: KVNamespace, params: Record<string, string>): Promise<Response> {
    return handleToken(
        new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ client_id: PROXY_CLIENT_ID, client_secret: 'us_secret', ...params }).toString(),
        }),
        kv,
        {}
    )
}

let kv: KVNamespace

beforeEach(async () => {
    kv = createInMemoryKV()
    await kv.put(`client:${PROXY_CLIENT_ID}`, JSON.stringify(MAPPING))
})

afterEach(() => {
    vi.unstubAllGlobals()
})

describe('a client shared by users in both regions', () => {
    it('routes each authorization code to the region that issued it, whatever the client_id selection says', async () => {
        const fetchMock = stubRegions({ code_eu: 'eu', code_us: 'us' })

        // The EU user starts first, then a US user starts before the EU user finishes,
        // overwriting the client_id selection with "us".
        const euFlow = await authorize(kv, 'eu', 'eu_state')
        const usFlow = await authorize(kv, 'us', 'us_state')
        await callback(kv, euFlow, 'code=code_eu')
        await callback(kv, usFlow, 'code=code_us')

        const euResponse = await token(kv, {
            grant_type: 'authorization_code',
            code: 'code_eu',
            redirect_uri: CLIENT_REDIRECT_URI,
        })
        expect(euResponse.status).toBe(200)
        expect(((await euResponse.json()) as Record<string, string>).access_token).toBe('pha_eu_code_eu')

        const usResponse = await token(kv, {
            grant_type: 'authorization_code',
            code: 'code_us',
            redirect_uri: CLIENT_REDIRECT_URI,
        })
        expect(usResponse.status).toBe(200)
        expect(((await usResponse.json()) as Record<string, string>).access_token).toBe('pha_us_code_us')

        expect(fetchMock).toHaveBeenCalledTimes(2)
        const euCall = new URLSearchParams(String(fetchMock.mock.calls[0]![1]!.body))
        expect(String(fetchMock.mock.calls[0]![0])).toMatch(/^https:\/\/eu\.posthog\.com/)
        expect(euCall.get('client_id')).toBe('shared_eu_client')
        expect(euCall.get('client_secret')).toBe('eu_secret')
        expect(euCall.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/shared_eu_client/')
    })

    it("retries a refresh in the other region when the client_id selection names another user's region", async () => {
        const fetchMock = stubRegions({ rt_eu: 'eu' })
        await kv.put(`region:${await hashKey(PROXY_CLIENT_ID)}`, 'us')

        const response = await token(kv, { grant_type: 'refresh_token', refresh_token: 'rt_eu' })

        expect(response.status).toBe(200)
        expect(((await response.json()) as Record<string, string>).access_token).toBe('pha_eu_rt_eu')
        expect(fetchMock.mock.calls.map(([url]) => new URL(String(url)).hostname)).toEqual([
            'us.posthog.com',
            'eu.posthog.com',
        ])
        expect(await kv.get(`region:${await hashKey(PROXY_CLIENT_ID)}`)).toBe('eu')
    })

    it('does not try the other region when the selected region accepts the refresh', async () => {
        const fetchMock = stubRegions({ rt_us: 'us' })
        await kv.put(`region:${await hashKey(PROXY_CLIENT_ID)}`, 'us')

        const response = await token(kv, { grant_type: 'refresh_token', refresh_token: 'rt_us' })

        expect(response.status).toBe(200)
        expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('returns the client error when neither region accepts the refresh', async () => {
        stubRegions({})
        await kv.put(`region:${await hashKey(PROXY_CLIENT_ID)}`, 'eu')

        const response = await token(kv, { grant_type: 'refresh_token', refresh_token: 'rt_revoked' })

        expect(response.status).toBe(400)
        expect(((await response.json()) as Record<string, string>).error).toBe('invalid_grant')
    })

    it('falls back to the client_id selection for a code whose flow predates per-code routing', async () => {
        const fetchMock = stubRegions({ legacy_code: 'eu' })
        const flow = {
            nonce: 'legacy_nonce',
            callbackUrl: 'https://oauth.posthog.com/oauth/callback/shared_eu_client/',
        }
        await putPendingCallback(kv, new URL(flow.callbackUrl).pathname, flow.nonce, {
            redirect_uri: CLIENT_REDIRECT_URI,
            state: 'orig',
        })
        await kv.put(`region:${await hashKey(PROXY_CLIENT_ID)}`, 'eu')
        await kv.put(`callback:${await hashKey(PROXY_CLIENT_ID)}`, CLIENT_REDIRECT_URI)

        await callback(kv, flow, 'code=legacy_code')
        expect(await kv.get(`code_route:${await hashKey('legacy_code')}`)).toBeNull()

        const response = await token(kv, {
            grant_type: 'authorization_code',
            code: 'legacy_code',
            redirect_uri: CLIENT_REDIRECT_URI,
        })
        expect(response.status).toBe(200)
        expect(String(fetchMock.mock.calls[0]![0])).toMatch(/^https:\/\/eu\.posthog\.com/)
    })

    it('ignores a code route recorded by a flow for a different client', async () => {
        const fetchMock = stubRegions({ victim_code: 'us' })
        await kv.put(`client:other_client`, JSON.stringify({ ...MAPPING, us_client_id: 'other_client' }))
        const attackerFlow = await handleAuthorize(
            new Request(
                `https://oauth.posthog.com/oauth/authorize/?client_id=other_client` +
                    `&redirect_uri=${encodeURIComponent(CLIENT_REDIRECT_URI)}&response_type=code&state=x&_region=eu`
            ),
            kv
        ).then((r) => {
            const regionalParams = new URL(r.headers.get('location')!).searchParams
            return { nonce: regionalParams.get('state')!, callbackUrl: regionalParams.get('redirect_uri')! }
        })
        await callback(kv, attackerFlow, 'code=victim_code')
        await kv.put(`region:${await hashKey(PROXY_CLIENT_ID)}`, 'us')
        await kv.put(`callback:${await hashKey(PROXY_CLIENT_ID)}`, CLIENT_REDIRECT_URI)

        const response = await token(kv, {
            grant_type: 'authorization_code',
            code: 'victim_code',
            redirect_uri: CLIENT_REDIRECT_URI,
        })

        expect(response.status).toBe(200)
        expect(String(fetchMock.mock.calls[0]![0])).toMatch(/^https:\/\/us\.posthog\.com/)
    })

    it('records nothing for a callback that carries an error instead of a code', async () => {
        const flow = await authorize(kv, 'eu', 'denied_state')
        const response = await callback(kv, flow, 'error=access_denied')

        expect(response.status).toBe(302)
        expect(new URL(response.headers.get('location')!).searchParams.get('error')).toBe('access_denied')
        const puts = vi.mocked(kv.put).mock.calls.map(([key]) => key as string)
        expect(puts.some((key) => key.startsWith('code_route:'))).toBe(false)
    })
})
