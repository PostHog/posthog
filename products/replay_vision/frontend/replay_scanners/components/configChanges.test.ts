import { describeTagOp, formatChangeValue, parseConfigChanges } from './configChanges'

describe('configChanges', () => {
    it('parses a well-formed change list and drops junk', () => {
        const parsed = parseConfigChanges([
            { field: 'tags', kind: 'tags', op: 'add', before: null, after: 'checkout', rationale: 'r' },
            { nope: true },
            'garbage',
        ])
        expect(parsed).toHaveLength(1)
        expect(parsed[0].kind).toBe('tags')
    })

    it('returns [] for non-array input', () => {
        expect(parseConfigChanges(undefined)).toEqual([])
        expect(parseConfigChanges({})).toEqual([])
    })

    it('drops entries whose kind or op is not a recognized value', () => {
        const parsed = parseConfigChanges([
            { field: 'tags', kind: 'bogus', op: 'add', before: null, after: 'a' },
            { field: 'tags', kind: 'tags', op: 'bogus', before: null, after: 'a' },
            { field: 'prompt', kind: 'prompt', op: 'set', before: 'old', after: 'new' },
        ])
        expect(parsed).toHaveLength(1)
        expect(parsed[0].field).toBe('prompt')
    })

    it('describes tag ops', () => {
        expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'add', before: null, after: 'a' }).verb).toBe('Add')
        expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'remove', before: 'b', after: null }).verb).toBe(
            'Remove'
        )
        expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'rename', before: 'b', after: 'c' }).text).toContain(
            'b'
        )
        expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'rename', before: 'b', after: 'c' }).text).toContain(
            'c'
        )
    })

    // A scorer's scale change carries `{min, max, label}` objects; without object-aware formatting the card printed "[object Object]".
    it.each([
        ['boolean on', true, 'on'],
        ['boolean off', false, 'off'],
        ['string', 'long', 'long'],
        ['scale without label', { min: 1, max: 5 }, '1-5'],
        ['scale with label', { min: 0, max: 10, label: 'frustration' }, '0-10 (frustration)'],
    ])('formats %s', (_name, value, expected) => {
        expect(formatChangeValue(value)).toBe(expected)
    })
})
