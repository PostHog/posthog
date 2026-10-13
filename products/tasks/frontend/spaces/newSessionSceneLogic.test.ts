import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceSource, newSessionSpace } from './newSessionSceneLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole }) as ChannelDTOApi

const SPACES = [space('general', 'general'), space('me', 'personal'), space('checkout')]

describe('newSessionSpace', () => {
    it.each<[string, string | null, string | null, string, NewSessionSpaceSource]>([
        ['a space’s own New session wins over the last space', 'checkout', 'general', 'checkout', 'route'],
        ['a generic New session uses the last space', null, 'checkout', 'checkout', 'last_used'],
        ['a generic New session with no last space uses personal', null, null, 'me', 'personal'],
        ['a deleted last space falls back to personal', null, 'gone', 'me', 'personal'],
        ['a deleted route space falls back to the last space', 'gone', 'checkout', 'checkout', 'last_used'],
    ])('%s', (_, routeSpaceId, lastSpaceId, expectedId, expectedSource) => {
        const { space: chosen, source } = newSessionSpace(SPACES, routeSpaceId, lastSpaceId)
        expect({ id: chosen?.id, source }).toEqual({ id: expectedId, source: expectedSource })
    })
})
