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
})
