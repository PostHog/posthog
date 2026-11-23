import { changeRequestErrors } from './askForChangeLogic'

const manyValues = (count: number): Record<string, string> =>
    Object.fromEntries(Array.from({ length: count }, (_, index) => [`field_${index}`, 'x']))

describe('changeRequestErrors', () => {
    it.each([
        ['an empty note', { note: '  ', values: {} }, { note: 'Describe the change you want.' }],
        ['a note at the limit', { note: 'a'.repeat(4000), values: {} }, {}],
        [
            'a note past the limit',
            { note: 'a'.repeat(4001), values: {} },
            { note: 'Shorten the description to 4,000 characters or fewer. It has 4,001.' },
        ],
        ['50 values', { note: 'ok', values: manyValues(50) }, {}],
        ['51 values with one left empty', { note: 'ok', values: { ...manyValues(50), blank: ' ' } }, {}],
        [
            '51 values',
            { note: 'ok', values: manyValues(51) },
            { values: 'Fill in at most 50 values. Describe the other changes in the description.' },
        ],
        [
            'a path past the limit',
            { note: 'ok', values: { ['a'.repeat(501)]: 'x' } },
            {
                values: 'A field path is longer than 500 characters. Clear its value and describe that change in the description.',
            },
        ],
    ])('answers %s', (_, form, expected) => {
        const errors = changeRequestErrors(form)
        expect(Object.fromEntries(Object.entries(errors).filter(([, error]) => error !== undefined))).toEqual(expected)
    })
})
