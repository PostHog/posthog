import { quarantineAuthor } from './quarantineAuthor'

const ALICE = { id: 1, first_name: 'Alice', email: 'alice@example.com' }

describe('quarantineAuthor', () => {
    it.each([
        { name: 'a user by first name', quarantine: { created_by: ALICE, source: 'human' }, expected: 'Alice' },
        {
            name: 'a user without a first name by email',
            quarantine: { created_by: { ...ALICE, first_name: '' }, source: 'human' },
            expected: 'alice@example.com',
        },
        {
            name: 'an automatic quarantine',
            quarantine: { created_by: null, source: 'auto' },
            expected: 'Quarantined automatically',
        },
        { name: 'nobody known', quarantine: { created_by: null, source: 'human' }, expected: null },
    ])('$name', ({ quarantine, expected }) => {
        expect(quarantineAuthor(quarantine)).toEqual(expected)
    })
})
