import { describe, expect, it, vi } from 'vitest'

import { handleCallback } from '@/handlers/callback'
import { putPendingCallback } from '@/lib/kv'

import { createInMemoryKV } from './helpers'

const CLIENT_CALLBACK_PATH = '/oauth/callback/client_us/'
const CLIENT_REDIRECT_URI = 'http://localhost:3000/callback'

async function pendingRecord(kv: KVNamespace, nonce: string, state: string | null): Promise<void> {
    await putPendingCallback(kv, CLIENT_CALLBACK_PATH, nonce, { redirect_uri: CLIENT_REDIRECT_URI, state })
}

function callbackRequest(query: string, path: string = CLIENT_CALLBACK_PATH): Request {
    return new Request(`https://oauth.posthog.com${path}?${query}`)
}

function redirectLocation(response: Response): URL {
    return new URL(response.headers.get('location')!)
}

describe('handleCallback', () => {
    it("redirects to original redirect_uri with code and the client's original state", async () => {
        const kv = createInMemoryKV()
        await pendingRecord(kv, 'proxy_nonce_123', 'test_state_123')

        const response = await handleCallback(callbackRequest('code=auth_code_abc&state=proxy_nonce_123'), kv)

        expect(response.status).toBe(302)
        const location = redirectLocation(response)
        expect(location.origin + location.pathname).toBe(CLIENT_REDIRECT_URI)
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('test_state_123')
    })

    it('deletes the flow record after reading it, so the nonce is single-use', async () => {
        const kv = createInMemoryKV()
        await pendingRecord(kv, 'single_use_nonce', 'orig_state')
        const request = callbackRequest('code=auth_code_abc&state=single_use_nonce')

        const first = await handleCallback(request, kv)
        const second = await handleCallback(request, kv)

        expect(first.status).toBe(302)
        expect(second.status).toBe(400)
        expect(await second.text()).toBe('State expired or invalid')
    })

    it('still redirects to the client when deleting the flow record fails', async () => {
        const kv = createInMemoryKV()
        await pendingRecord(kv, 'delete_fails_nonce', 'orig_state')
        vi.mocked(kv.delete).mockRejectedValue(new Error('KV transient failure'))

        const response = await handleCallback(callbackRequest('code=auth_code_abc&state=delete_fails_nonce'), kv)

        expect(response.status).toBe(302)
        const location = redirectLocation(response)
        expect(location.origin + location.pathname).toBe(CLIENT_REDIRECT_URI)
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('orig_state')
    })

    it('carries no state param when the flow record has no client state', async () => {
        const kv = createInMemoryKV()
        await pendingRecord(kv, 'nonce_no_state', null)

        const response = await handleCallback(callbackRequest('code=auth_code_abc&state=nonce_no_state'), kv)

        expect(response.status).toBe(302)
        const location = redirectLocation(response)
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.has('state')).toBe(false)
    })

    it.each([
        ['a path that names no client', callbackRequest('code=c&state=s', '/oauth/callback/'), 'Unknown callback path'],
        ['a missing state', callbackRequest('code=auth_code_abc'), 'Missing state parameter'],
        [
            'an expired or unknown nonce',
            callbackRequest('code=auth_code_abc&state=expired'),
            'State expired or invalid',
        ],
    ])('returns 400 for %s', async (_name, request, message) => {
        const kv = createInMemoryKV()

        const response = await handleCallback(request, kv)

        expect(response.status).toBe(400)
        expect(await response.text()).toBe(message)
    })

    it("forwards error params to the client's redirect_uri and restores its original state", async () => {
        const kv = createInMemoryKV()
        await pendingRecord(kv, 'err_nonce', 'client_err_state')

        const response = await handleCallback(
            callbackRequest('error=access_denied&error_description=User+denied+access&state=err_nonce'),
            kv
        )

        expect(response.status).toBe(302)
        const location = redirectLocation(response)
        expect(location.searchParams.get('error')).toBe('access_denied')
        expect(location.searchParams.get('error_description')).toBe('User denied access')
        expect(location.searchParams.get('state')).toBe('client_err_state')
    })
})
