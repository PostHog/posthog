import { SELF } from 'cloudflare:test'
import { describe, expect, it, vi } from 'vitest'

describe('Health endpoint', () => {
    it.each([{ path: '/health' }, { path: '/healthz' }])(
        'returns 200 with JSON status on $path without auth',
        async ({ path }) => {
            const response = await SELF.fetch(`https://mcp.posthog.com${path}`)

            expect(response.status).toBe(200)
            expect(response.headers.get('content-type')).toContain('application/json')
            expect(response.headers.get('cache-control')).toBe('no-store')
            expect(await response.json()).toEqual({ status: 'ok' })
        }
    )
})

describe('CLI tool catalog', () => {
    it('passes the catalog through to the Hono server of the region without asking for a token', async () => {
        // Built per call: a Workers response can only be read in the request that created it.
        const upstream = vi
            .spyOn(globalThis, 'fetch')
            .mockImplementation(async () => Response.json({ schemaVersion: 1 }))
        try {
            const response = await SELF.fetch('https://mcp-eu.posthog.com/cli/catalog.json')

            expect(response.status).toBe(200)
            expect(await response.json()).toEqual({ schemaVersion: 1 })
            expect(String(upstream.mock.calls[0]?.[0])).toContain('/cli/catalog.json')
        } finally {
            upstream.mockRestore()
        }
    })
})
