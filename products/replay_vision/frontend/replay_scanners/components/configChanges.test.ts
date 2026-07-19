import {
    buildAppliedConfig,
    changedFields,
    describeTagOp,
    formatChangeValue,
    parseConfigChanges,
} from './configChanges'

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

    it('lists distinct changed fields with their kind, in first-seen order', () => {
        expect(
            changedFields([
                { field: 'prompt', kind: 'prompt', op: 'set', before: 'a', after: 'b' },
                { field: 'tags', kind: 'tags', op: 'add', before: null, after: 'x' },
                { field: 'tags', kind: 'tags', op: 'remove', before: 'y', after: null },
            ])
        ).toEqual([
            { field: 'prompt', kind: 'prompt' },
            { field: 'tags', kind: 'tags' },
        ])
    })

    it.each([
        [
            'approved uses the edited value',
            { prompt: { approved: true, value: 'edited' } },
            { prompt: 'edited', tags: ['a'] },
        ],
        [
            'rejected falls back to base',
            { prompt: { approved: false, value: 'edited' } },
            { prompt: 'base', tags: ['a'] },
        ],
    ])('buildAppliedConfig: %s', (_name, decisions, expected) => {
        expect(buildAppliedConfig({ prompt: 'base', tags: ['a'] }, decisions)).toEqual(expected)
    })

    it('buildAppliedConfig only touches decided fields, leaving the rest of base intact', () => {
        const applied = buildAppliedConfig(
            { prompt: 'base', tags: ['a', 'b'], multi_label: true },
            { tags: { approved: true, value: ['a', 'c'] } }
        )
        expect(applied).toEqual({ prompt: 'base', tags: ['a', 'c'], multi_label: true })
    })
})
