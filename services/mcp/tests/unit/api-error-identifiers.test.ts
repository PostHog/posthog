import { describe, expect, it } from 'vitest'

import { parseApiErrorIdentifiers } from '@/lib/errors'

describe('parseApiErrorIdentifiers', () => {
    it.each([
        [
            'a DRF validation body',
            '{"type":"validation_error","code":"invalid_input","detail":"x","attr":"actions__0__name"}',
            { code: 'invalid_input', attr: 'actions__0__name' },
        ],
        ['a {code, message} body', '{"code":"credentials_invalid","message":"x"}', { code: 'credentials_invalid' }],
        [
            'the first item of a list',
            '[{"code":"required","attr":"name"},{"code":"other"}]',
            { code: 'required', attr: 'name' },
        ],
        ['a null attr', '{"code":"throttled","attr":null}', { code: 'throttled' }],
        ['a body without a code', '{"detail":"Not found."}', {}],
        ['a non-JSON body', '<html>Bad gateway</html>', {}],
        ['an empty body', '', {}],
        ['a JSON null', 'null', {}],
        ['an empty list', '[]', {}],
        ['a list of strings', '["a"]', {}],
        ['an overlong code', JSON.stringify({ code: `a${'b'.repeat(64)}` }), {}],
        ['a code with spaces', '{"code":"has spaces"}', {}],
        ['a code with punctuation', '{"code":"bad-code: x!"}', {}],
        ['a code that starts with a digit', '{"code":"1abc"}', {}],
        ['a numeric code', '{"code":42}', {}],
        ['an attr with punctuation', '{"code":"invalid","attr":"a.b; x"}', { code: 'invalid' }],
    ])('reads %s', (_label, body, expected) => {
        expect(parseApiErrorIdentifiers(body)).toEqual(expected)
    })

    it('accepts a code of exactly 64 characters', () => {
        const code = `a${'b'.repeat(63)}`
        expect(parseApiErrorIdentifiers(JSON.stringify({ code }))).toEqual({ code })
    })
})
