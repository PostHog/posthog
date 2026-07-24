import {
    buildAppliedConfig,
    changedFields,
    describeTagOp,
    fieldEditor,
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
        ['an edited field overlays the base', { prompt: 'edited' }, { prompt: 'edited', tags: ['a'] }],
        ['a field edited back to base is a no-op', { prompt: 'base' }, { prompt: 'base', tags: ['a'] }],
        ['no edits leaves the base untouched', {}, { prompt: 'base', tags: ['a'] }],
    ])('buildAppliedConfig: %s', (_name, fieldValues, expected) => {
        expect(buildAppliedConfig({ prompt: 'base', tags: ['a'] }, fieldValues)).toEqual(expected)
    })

    it.each([
        ['a mapped field', 'allow_inconclusive', true, 'flag'],
        ['an unknown boolean falls back to a flag', 'some_new_flag', false, 'flag'],
        ['an unknown string falls back to text', 'some_new_field', 'x', 'text'],
    ])('fieldEditor resolves %s', (_name, field, value, expectedKind) => {
        expect(fieldEditor(field, value).kind).toBe(expectedKind)
    })

    it('buildAppliedConfig only overlays the given fields, leaving the rest of base intact', () => {
        const applied = buildAppliedConfig(
            { prompt: 'base', tags: ['a', 'b'], multi_label: true },
            { tags: ['a', 'c'] }
        )
        expect(applied).toEqual({ prompt: 'base', tags: ['a', 'c'], multi_label: true })
    })
})
