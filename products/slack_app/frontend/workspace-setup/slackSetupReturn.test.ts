import { parseSlackSetupReturnTarget } from './slackSetupReturn'

describe('parseSlackSetupReturnTarget', () => {
    test.each([
        ['settings', 'settings'],
        ['https://example.com', undefined],
        ['/settings', undefined],
        ['toString', undefined],
        [undefined, undefined],
        [['settings'], undefined],
    ])('parses %p as %p', (value, expected) => {
        expect(parseSlackSetupReturnTarget(value)).toEqual(expected)
    })
})
