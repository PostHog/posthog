import { describe, expect, it } from 'vitest'

import { maskEmails, maskSqlLiterals } from '@/lib/pii-scrub'

describe('pii-scrub', () => {
    it.each([
        ['masks a plain string literal', "WHERE properties.email = 'john@acme.com'", "WHERE properties.email = '***'"],
        ['keeps wildcard structure on both sides', "name ILIKE '%john%'", "name ILIKE '%***%'"],
        ['keeps a leading-only wildcard', "name LIKE '%john'", "name LIKE '%***'"],
        ['keeps a trailing-only wildcard', "name LIKE 'john%'", "name LIKE '***%'"],
        ['keeps underscore wildcards', "name LIKE '_ohn%'", "name LIKE '_***%'"],
        ['keeps ISO dates — low PII, high analytic value', "timestamp >= '2026-07-01'", "timestamp >= '2026-07-01'"],
        ['keeps ISO datetimes', "timestamp < '2026-07-01 12:30:00'", "timestamp < '2026-07-01 12:30:00'"],
        ['masks literals with doubled-quote escapes', "name = 'O''Brien'", "name = '***'"],
        ['masks literals with backslash escapes', "name = 'a\\'b'", "name = '***'"],
        [
            'masks every literal independently',
            "event = 'purchase' AND name LIKE 'x%'",
            "event = '***' AND name LIKE '***%'",
        ],
        ['keeps empty literals', "coalesce(name, '')", "coalesce(name, '')"],
        ['keeps pure-wildcard literals', "name LIKE '%'", "name LIKE '%'"],
        [
            'leaves numbers and identifiers untouched',
            'SELECT count() FROM events LIMIT 100',
            'SELECT count() FROM events LIMIT 100',
        ],
    ])('%s', (_case, input, expected) => {
        expect(maskSqlLiterals(input)).toBe(expected)
    })

    it.each([
        ['masks emails in free text', 'find events for john@acme.com yesterday', 'find events for <email> yesterday'],
        ['leaves text without emails untouched', 'count yesterday signups', 'count yesterday signups'],
    ])('%s', (_case, input, expected) => {
        expect(maskEmails(input)).toBe(expected)
    })
})
