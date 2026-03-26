import { describe, expect, it } from 'vitest'

import worker from '@/index'

const mockEnv = {
    AUTH_KV: {} as KVNamespace,
}

describe('router', () => {
    it.each([
        ['/', 200, 'text/plain'],
        ['/.well-known/oauth-authorization-server', 200, 'application/json'],
    ])('GET %s returns %d', async (path, expectedStatus, expectedContentType) => {
        const request = new Request(`https://oauth.posthog.com${path}`)
        const response = await worker.fetch(request, mockEnv)
        expect(response.status).toBe(expectedStatus)
        expect(response.headers.get('content-type')).toContain(expectedContentType)
    })

    it('returns 404 for unknown paths', async () => {
        const request = new Request('https://oauth.posthog.com/unknown')
        const response = await worker.fetch(request, mockEnv)
        expect(response.status).toBe(404)
    })

    it('returns the landing page at /', async () => {
        const request = new Request('https://oauth.posthog.com/')
        const response = await worker.fetch(request, mockEnv)
        const text = await response.text()
        expect(text).toContain('PostHog OAuth Proxy')
    })
})
