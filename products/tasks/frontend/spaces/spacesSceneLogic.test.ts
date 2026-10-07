import { isLockedSpace, spaceLabel } from '~/layout/today/todaySpacesLogic'

import { ChannelDTOApi } from '../generated/api.schemas'
import { spacesIndexLists } from './spacesSceneLogic'

const space = (id: string, name: string, starred: boolean, system_role: string | null = null): ChannelDTOApi =>
    ({ id, name, starred, system_role }) as ChannelDTOApi

const SPACES = [
    space('general', 'general', false, 'general'),
    space('me', 'me', false, 'personal'),
    space('checkout', 'checkout', true),
    space('billing', 'billing', false),
]

describe('spacesSceneLogic', () => {
    it.each([
        ['', ['me', 'checkout'], ['general', 'billing']],
        ['CHECK', ['checkout'], []],
        ['bill', [], ['billing']],
    ])('splits the spaces for the search %p', (search, starred, rest) => {
        const lists = spacesIndexLists(SPACES, search)

        expect(lists.starred.map((item) => item.id)).toEqual(starred)
        expect(lists.rest.map((item) => item.id)).toEqual(rest)
    })

    // The personal space comes back as `personal`, not `private`, and still shows a lock.
    it.each([
        ['the personal space', { channel_type: 'personal', system_role: 'personal' }, true],
        ['a private space', { channel_type: 'private', system_role: null }, true],
        ['a public space', { channel_type: 'public', system_role: null }, false],
        ['the general space', { channel_type: 'public', system_role: 'general' }, false],
    ])('locks %s: %s', (_, identity, locked) => {
        expect(isLockedSpace(identity as ChannelDTOApi)).toBe(locked)
    })

    // Matches PostHog Desktop, which names the personal space "personal" whatever its stored name is.
    it.each([
        ['the personal space', space('me', 'me', false, 'personal'), 'personal'],
        ['a shared space', space('billing', 'billing', false), 'billing'],
    ])('labels %s', (_, channel, label) => {
        expect(spaceLabel(channel)).toBe(label)
    })
})
