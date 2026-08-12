import { isValidCounterName } from './counter-name.js'

describe('isValidCounterName', () => {
    it.each([
        ['signups', true],
        ['billing-retries', true],
        ['', false],
        ['UPPERCASE', false],
        ['contains spaces', false],
        [`a${'b'.repeat(64)}`, false],
    ])('validates %j as %s', (name, expected) => {
        expect(isValidCounterName(name)).toBe(expected)
    })
})
