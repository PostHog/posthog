import { splitAtErrorSpan } from './sourceFilterErrorSpan'

describe('splitAtErrorSpan', () => {
    test.each([
        ['a span in the middle', 'a AND priorty = 1', 6, 13, { before: 'a AND ', marked: 'priorty', after: ' = 1' }],
        ['a span at the start', 'projct = 1', 0, 6, { before: '', marked: 'projct', after: ' = 1' }],
        ['a point at the end', 'a AND', 5, 5, { before: 'a AND', marked: '', after: '' }],
        [
            'a span after an emoji',
            "label = '😀' AND priorty = 1",
            16,
            23,
            { before: "label = '😀' AND ", marked: 'priorty', after: ' = 1' },
        ],
        ['a negative start', 'projct = 1', -2, 6, { before: '', marked: 'projct', after: ' = 1' }],
        ['an end before the start', 'a AND b', 4, 2, { before: 'a AN', marked: '', after: 'D b' }],
    ])('splits %s', (_, text, start, end, expected) => {
        expect(splitAtErrorSpan(text, { start, end })).toEqual(expected)
    })
})
