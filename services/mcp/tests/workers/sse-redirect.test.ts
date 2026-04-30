import { SELF } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

describe('SSE to MCP redirect', () => {
    it.each([
        { from: 'https://mcp.posthog.com/sse', toPath: '/mcp' },
        { from: 'https://mcp.posthog.com/sse/', toPath: '/mcp/' },
        { from: 'https://mcp.posthog.com/sse/message', toPath: '/mcp/message' },
        { from: 'https://mcp.posthog.com/sse?features=flags', toPath: '/mcp' },
        { from: 'https://mcp.posthog.com/sse?features=flags&region=eu', toPath: '/mcp' },
    ])('redirects $from to $toPath with 308 and tracking marker', async ({ from, toPath }) => {
        const response = await SELF.fetch(from, { redirect: 'manual' })

        expect(response.status).toBe(308)
        const location = new URL(response.headers.get('location')!)
        expect(location.pathname).toBe(toPath)
        // Tracking marker so /mcp can identify clients that came in via /sse.
        expect(location.searchParams.get('_deprecated')).toBe('sse')
        // Original query params are preserved.
        const originalParams = new URL(from).searchParams
        for (const [key, value] of originalParams) {
            expect(location.searchParams.get(key)).toBe(value)
        }
    })

    it('does not affect /mcp requests', async () => {
        const response = await SELF.fetch('https://mcp.posthog.com/mcp', { redirect: 'manual' })

        expect(response.status).not.toBe(308)
    })
})
