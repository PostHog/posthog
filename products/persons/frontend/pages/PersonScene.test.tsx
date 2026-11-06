import { scene } from './PersonScene'

describe('PersonScene', () => {
    // A distinct ID with a stray `%` (e.g. `50%off`) makes decodeURIComponent throw
    // `URIError: URI malformed`; paramsToProps must fall back to the raw id so the
    // scene still renders instead of hard-crashing.
    it.each<[string, string]>([
        ['50%25off', '50%off'], // valid encoding is decoded
        ['50%off', '50%off'], // malformed `%` falls back to the raw id
        ['foo bar', 'foo bar'], // whitespace passes through untouched
    ])('paramsToProps turns raw id %s into urlId %s without throwing', (rawUrlId, expected) => {
        expect(scene.paramsToProps?.({ params: { _: rawUrlId }, searchParams: {}, hashParams: {} })).toEqual({
            syncWithUrl: true,
            urlId: expected,
        })
    })
})
