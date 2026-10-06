import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceSource, newSessionSpace } from './newSessionSceneLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole }) as ChannelDTOApi

const SPACES = [space('general', 'general'), space('me', 'personal'), space('checkout')]

describe('newSessionSpace', () => {
    it.each<[string, string | null, string, NewSessionSpaceSource]>([
        ['a space’s own New session keeps its space', 'checkout', 'checkout', 'route'],
        ['a generic New chat always starts personal', null, 'me', 'personal'],
        ['a deleted route space falls back to personal', 'gone', 'me', 'personal'],
    ])('%s', (_, routeSpaceId, expectedId, expectedSource) => {
        const { space: chosen, source } = newSessionSpace(SPACES, routeSpaceId)
        expect({ id: chosen?.id, source }).toEqual({ id: expectedId, source: expectedSource })
    })
})
