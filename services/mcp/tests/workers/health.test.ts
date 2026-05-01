import { SELF } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

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
