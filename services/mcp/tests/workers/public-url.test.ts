import { SELF } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

// Cloudflare hands the worker the URL the client connected to. A client-sent
// X-Forwarded-Host must not replace that host in anything the worker advertises.
describe('public URL on the edge worker', () => {
    const headers = { 'X-Forwarded-Host': 'mcp-eu.posthog.com' }

    it('keeps the request host in protected resource metadata', async () => {
        const response = await SELF.fetch('https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp', {
            headers,
        })

        expect(response.status).toBe(200)
        const body = (await response.json()) as { resource: string }
        expect(body.resource).toBe('https://mcp.posthog.com/mcp')
    })

    it('keeps the request host and region in the 401 challenge', async () => {
        const response = await SELF.fetch('https://mcp.posthog.com/mcp', { method: 'POST', headers })

        expect(response.status).toBe(401)
        expect(response.headers.get('WWW-Authenticate')).toBe(
            'Bearer resource_metadata="https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp"'
        )
    })

    it('keeps the request host in the SSE redirect', async () => {
        const response = await SELF.fetch('https://mcp.posthog.com/sse', { headers, redirect: 'manual' })

        expect(response.status).toBe(308)
        expect(new URL(response.headers.get('location')!).host).toBe('mcp.posthog.com')
    })
})
