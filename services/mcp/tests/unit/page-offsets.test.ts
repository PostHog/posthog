import { describe, expect, it } from 'vitest'

import { withPageOffsets } from '@/tools/tool-utils'

describe('withPageOffsets', () => {
    it.each([
        [
            'an absolute link built from a cluster-internal host',
            'http://posthog-api.internal:8000/api/projects/1/conversations/tickets/?limit=50&offset=100',
            100,
        ],
        ['a relative link', '/api/projects/1/conversations/tickets/?limit=50&offset=50', 50],
        ['a link without an offset param', 'https://us.posthog.com/api/projects/1/persons/', null],
        ['no link', null, null],
    ])('reads the next offset from %s', (_case, link, expected) => {
        expect(withPageOffsets({ count: 200, next: link, previous: null, results: [] })).toEqual({
            count: 200,
            next_offset: expected,
            previous_offset: null,
            results: [],
        })
    })

    it('reads a previous link without an offset param as the first page', () => {
        const envelope = withPageOffsets({
            count: 200,
            next: null,
            previous: 'http://posthog-api.internal:8000/api/projects/1/persons/?limit=50',
            results: [],
        })

        expect(envelope.previous_offset).toBe(0)
    })

    it('leaves a response that is not an envelope alone', () => {
        expect(withPageOffsets([{ id: 'one' }])).toEqual([{ id: 'one' }])
    })
})
