import { describe, expect, it } from 'vitest'

import { getReadOnlyFromRequest } from '@/index'

describe('getReadOnlyFromRequest', () => {
    it.each([
        ['canonical x-posthog-readonly header', { 'x-posthog-readonly': 'true' }, ''],
        ['legacy x-posthog-read-only header', { 'x-posthog-read-only': '1' }, ''],
        ['readonly query parameter', {}, '?readonly=true'],
    ])('reads read-only from %s', (_, headers, qs) => {
        const request = new Request(`https://mcp.posthog.com/mcp${qs}`, { headers })

        expect(getReadOnlyFromRequest(request, new URL(request.url))).toBe(true)
    })
})
