import type { UserBasicApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutOwnerBubbles, scoutOwnersLabel, showsScoutOwnership } from './scoutOwners'

function owner(overrides: Partial<UserBasicApi> & Pick<UserBasicApi, 'email'>): UserBasicApi {
    return {
        id: 1,
        uuid: '00000000-0000-0000-0000-000000000000',
        first_name: '',
        last_name: '',
        hedgehog_config: null,
        ...overrides,
    }
}

describe('scoutOwners', () => {
    it.each([
        ['custom', true],
        ['canonical', false],
    ] as const)('shows ownership for a %s scout: %s', (scout_origin, expected) => {
        expect(showsScoutOwnership({ scout_origin })).toBe(expected)
    })

    it('labels a single owner by name and several by count', () => {
        const ada = owner({ email: 'ada@example.com', first_name: 'Ada', last_name: 'Ellis' })
        expect(scoutOwnersLabel([ada])).toBe('Ada Ellis')
        expect(scoutOwnersLabel([ada, owner({ email: 'bo@example.com' })])).toBe('2 owners')
    })

    it('falls back to the email for an owner who never set a name', () => {
        // Invited-but-unnamed members are common, and an avatar with a blank label names nobody.
        const nameless = owner({ email: 'bo@example.com' })
        expect(scoutOwnersLabel([nameless])).toBe('bo@example.com')
        expect(scoutOwnerBubbles([nameless])).toEqual([
            { email: 'bo@example.com', name: 'bo@example.com', title: 'bo@example.com' },
        ])
    })

    it('puts the email in the hover title next to a name', () => {
        expect(scoutOwnerBubbles([owner({ email: 'ada@example.com', first_name: 'Ada', last_name: 'Ellis' })])).toEqual(
            [{ email: 'ada@example.com', name: 'Ada Ellis', title: 'Ada Ellis (ada@example.com)' }]
        )
    })
})
