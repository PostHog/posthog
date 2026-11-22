import { fitReportTagCount } from './reportTagFit'

describe('fitReportTagCount', () => {
    test.each([
        { name: 'every tag fits', tagWidths: [40, 40], available: 100, minimum: 0, expected: 2 },
        {
            name: 'the last tag takes the place of a +1 chip',
            tagWidths: [50, 10],
            available: 65,
            minimum: 0,
            expected: 2,
        },
        { name: 'leaves room for the +n chip', tagWidths: [40, 40, 40], available: 100, minimum: 0, expected: 1 },
        {
            name: 'shows only +n when no tag fits beside it',
            tagWidths: [80, 40],
            available: 60,
            minimum: 0,
            expected: 0,
        },
        {
            name: 'keeps the selected tags even when they do not fit',
            tagWidths: [80, 80, 40],
            available: 60,
            minimum: 2,
            expected: 2,
        },
        { name: 'no tags', tagWidths: [], available: 0, minimum: 0, expected: 0 },
    ])('$name', ({ tagWidths, available, minimum, expected }) => {
        expect(fitReportTagCount({ tagWidths, overflowWidth: 20, available, gap: 4, minimum })).toBe(expected)
    })
})
