import { describe, expect, it } from 'vitest'

import { sanitizeHeaderValue } from '@/lib/utils'

describe('utils', () => {
    describe('sanitizeHeaderValue', () => {
        it.each([
            ['passthrough', 'posthog/wizard 1.0', 'posthog/wizard 1.0'],
            ['strips control chars', 'agent\x00with\x1fnulls', 'agentwithnulls'],
            ['strips DEL character', 'hello\x7fworld', 'helloworld'],
            ['truncates to max length', 'a'.repeat(1500), 'a'.repeat(1000)],
            ['trims whitespace', '  spaces  ', 'spaces'],
            ['strips then trims', '\x00  hello  \x1f', 'hello'],
            ['whitespace only is undefined', ' ', undefined],
            ['undefined is undefined', undefined, undefined],
        ])('%s', (_name, input, expected) => {
            expect(sanitizeHeaderValue(input)).toBe(expected)
        })
    })
})
