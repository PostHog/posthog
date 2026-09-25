import { describe, expect, it } from 'vitest'

import { classifyRequestCharge } from '@/hono/request-cost'

describe('classifyRequestCharge', () => {
    it.each([
        { methods: ['initialize'], expected: 'handshake' },
        { methods: ['server/discover'], expected: 'handshake' },
        { methods: ['notifications/initialized'], expected: 'handshake' },
        { methods: ['ping'], expected: 'handshake' },
        { methods: ['tools/list'], expected: 'handshake' },
        { methods: ['initialize', 'notifications/initialized', 'tools/list'], expected: 'handshake' },
        { methods: ['tools/call'], expected: 'work' },
        { methods: ['resources/read'], expected: 'work' },
        // One tool call in a batch makes the whole request work.
        { methods: ['initialize', 'tools/call'], expected: 'work' },
        // An unparseable body must never buy the cheaper bucket.
        { methods: [], expected: 'work' },
    ])('charges $methods to the $expected bucket', ({ methods, expected }) => {
        expect(classifyRequestCharge(methods)).toBe(expected)
    })
})
