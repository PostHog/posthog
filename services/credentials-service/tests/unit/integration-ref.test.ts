import { describe, expect, it } from 'vitest'

import { formatIntegrationRef, parseIntegrationRef } from '@/db/integrations'

const UUID = '0b6f4f8e-2c1a-4d3e-9f7a-5b8c9d0e1f2a'

// Each row has exactly one stored form, so a reference the Python SDK writes must parse here,
// and a form it never writes must not.
describe('parseIntegrationRef', () => {
    it.each([
        ['0', { legacyId: 0 }],
        ['123', { legacyId: 123 }],
        [String(Number.MAX_SAFE_INTEGER), { legacyId: Number.MAX_SAFE_INTEGER }],
        [UUID, { id: UUID }],
    ])('parses %j', (value, expected) => {
        expect(parseIntegrationRef(value)).toEqual(expected)
        expect(formatIntegrationRef(parseIntegrationRef(value)!)).toBe(value)
    })

    it.each([
        ['an empty string', ''],
        ['a leading zero', '0123'],
        ['a sign', '+5'],
        ['a negative id', '-5'],
        ['whitespace', ' 5'],
        ['a decimal point', '5.0'],
        ['an id past the safe integer range', '9007199254740993'],
        ['an uppercase UUID', UUID.toUpperCase()],
        ['a UUID without hyphens', UUID.replaceAll('-', '')],
        ['a braced UUID', `{${UUID}}`],
        ['non-ASCII digits', '١٢٣'],
    ])('rejects %s', (_label, value) => {
        expect(parseIntegrationRef(value)).toBeNull()
    })
})
