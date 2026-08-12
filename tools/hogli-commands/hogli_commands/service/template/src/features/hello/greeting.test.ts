import { greetingFor } from './greeting.js'

describe('greetingFor', () => {
    it.each([
        ['Ada', 'Hello, Ada.'],
        ['  Ada  ', 'Hello, Ada.'],
        ['', null],
        ['a'.repeat(65), null],
    ])('maps %j to %j', (name, expected) => {
        expect(greetingFor(name)).toBe(expected)
    })
})
