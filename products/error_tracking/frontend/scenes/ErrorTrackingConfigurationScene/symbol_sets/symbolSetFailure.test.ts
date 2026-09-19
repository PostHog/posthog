import { symbolSetFailureMessage } from './symbolSetFailure'

describe('symbolSetFailureMessage', () => {
    it.each([
        [null, null],
        ['', null],
    ])('returns null for %p', (stored, expected) => {
        expect(symbolSetFailureMessage(stored)).toBe(expected)
    })

    it.each([
        [
            'a newtype variant',
            '{"JavaScript":{"NoSourcemap":"https://example.com/app.js"}}',
            'PostHog found no source map for https://example.com/app.js. Upload one, or check that your build writes a sourceMappingURL comment.',
        ],
        [
            'a unit variant',
            '{"JavaScript":"NoUrlOrChunkId"}',
            'This stack frame had no source URL and no chunk ID, so there was nothing to look up.',
        ],
        [
            'a tuple variant',
            '{"JavaScript":{"TokenNotFound":["app.js",12,34]}}',
            'The source map has no entry for app.js line 12, column 34.',
        ],
        [
            'a tuple variant whose message reorders the payload',
            '{"JavaScript":{"HttpStatus":[404,"https://example.com/app.js.map"]}}',
            'Fetching https://example.com/app.js.map returned HTTP 404.',
        ],
        [
            'a top level variant',
            '{"MissingChunkIdData":"01920000-0000-0000-0000-000000000000"}',
            'No symbol set was uploaded for chunk ID 01920000-0000-0000-0000-000000000000.',
        ],
        [
            'a numeric address payload',
            '{"Apple":{"SymbolNotFound":4276092}}',
            'The uploaded dSYM has no symbol at address 0x413f7c.',
        ],
        [
            'a nested data error',
            '{"Hermes":{"DataError":{"WrongVersion":[1,2]}}}',
            'PostHog could not read the uploaded file. Upload it again with the latest PostHog CLI.',
        ],
    ])('translates %s', (_name, stored, expected) => {
        expect(symbolSetFailureMessage(stored)).toBe(expected)
    })

    it.each([
        [
            'an unmapped variant of a known language',
            '{"JavaScript":{"SomeNewFailure":"detail"}}',
            'Some new failure: detail.',
        ],
        ['an unmapped language', '{"Zig":"NoTape"}', 'No tape.'],
    ])('keeps %s readable', (_name, stored, expected) => {
        expect(symbolSetFailureMessage(stored)).toBe(expected)
    })

    it('leaves a reason that is not serialized json as it is', () => {
        expect(symbolSetFailureMessage('Source map not found')).toBe('Source map not found')
    })
})
