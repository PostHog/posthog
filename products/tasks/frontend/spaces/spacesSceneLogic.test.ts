import { expectLogic } from 'kea-test-utils'

import { isLockedSpace, spaceLabel } from '~/layout/today/todaySpacesLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ChannelDTOApi } from '../generated/api.schemas'
import { spacesIndexLists, spacesSceneLogic } from './spacesSceneLogic'

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

    it('shows a person whose only recent task is past the first page of tasks', async () => {
        const recent = new Date(Date.now() - 60_000).toISOString()
        const task = (channel: string, uuid: string): Record<string, unknown> => ({
            channel,
            archived: false,
            last_activity_at: recent,
            created_by: { id: 1, uuid, first_name: uuid, email: `${uuid}@example.com` },
        })
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
                    return offset === 0
                        ? [200, { next: 'next-page', results: [task('checkout', 'ada')] }]
                        : [200, { next: null, results: [task('billing', 'grace')] }]
                },
            },
        })
        initKeaTests()
        const logic = spacesSceneLogic()
        logic.mount()
        logic.actions.loadSpacePresence()
        await expectLogic(logic).toDispatchActions(['loadSpacePresenceSuccess'])

        expect(logic.values.spacePresence['billing']?.people.map((person) => person.uuid)).toEqual(['grace'])
    })
})
