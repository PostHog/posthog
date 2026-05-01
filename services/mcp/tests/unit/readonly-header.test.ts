import { describe, expect, it } from 'vitest'

import { getReadOnlyFromRequest } from '@/index'

describe('getReadOnlyFromRequest', () => {
    it('reads the canonical readonly header', () => {
        const request = new Request('https://mcp.posthog.com/mcp', {
            headers: { 'x-posthog-readonly': 'true' },
        })

        expect(getReadOnlyFromRequest(request, new URL(request.url))).toBe(true)
    })

    it('accepts the legacy read-only header for compatibility', () => {
        const request = new Request('https://mcp.posthog.com/mcp', {
            headers: { 'x-posthog-read-only': '1' },
        })

        expect(getReadOnlyFromRequest(request, new URL(request.url))).toBe(true)
    })

    it('falls back to the readonly query parameter', () => {
        const request = new Request('https://mcp.posthog.com/mcp?readonly=true')

        expect(getReadOnlyFromRequest(request, new URL(request.url))).toBe(true)
    })
})
