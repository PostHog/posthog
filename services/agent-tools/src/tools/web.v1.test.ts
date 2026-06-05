import { vi } from 'vitest'

import type { HttpFetcher } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { webFetchV1 } from './web-fetch.v1'
import { setWebSearchProvider, webSearchV1 } from './web-search.v1'

describe('@posthog/web-fetch', () => {
    it('returns status, body, content_type', async () => {
        const http: HttpFetcher = {
            fetch: vi.fn(
                async () =>
                    ({
                        ok: true,
                        status: 200,
                        text: async () => '<html></html>',
                        headers: { get: (k: string) => (k === 'content-type' ? 'text/html' : null) },
                    }) as unknown as Response
            ),
        }
        const out = await webFetchV1.run({ url: 'https://example.com', max_bytes: 1_000_000 }, makeCtx({ http }))
        expect(out.status).toBe(200)
        expect(out.body).toBe('<html></html>')
        expect(out.content_type).toBe('text/html')
    })

    it('truncates body to max_bytes', async () => {
        const big = 'x'.repeat(10_000)
        const http: HttpFetcher = {
            fetch: vi.fn(
                async () =>
                    ({
                        ok: true,
                        status: 200,
                        text: async () => big,
                        headers: { get: () => null },
                    }) as unknown as Response
            ),
        }
        const out = await webFetchV1.run({ url: 'https://example.com', max_bytes: 100 }, makeCtx({ http }))
        expect(out.body.length).toBe(100)
    })
})

describe('@posthog/web-search', () => {
    it('returns provider results', async () => {
        setWebSearchProvider({
            async search(q: string) {
                return [{ title: `result for ${q}`, url: 'https://x.com', snippet: 'snip' }]
            },
        })
        const out = await webSearchV1.run({ query: 'posthog', limit: 5 }, makeCtx())
        expect(out.results).toHaveLength(1)
        expect(out.results[0].title).toBe('result for posthog')
    })
})
