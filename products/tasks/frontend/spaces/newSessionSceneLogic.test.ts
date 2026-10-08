import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceSource, newSessionSpace } from './newSessionSceneLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole }) as ChannelDTOApi

describe('newSessionSpace', () => {
    it.each<[string, ChannelDTOApi[], string | undefined, NewSessionSpaceSource | null]>([
        [
            'starts personal even when a team space comes first',
            [space('general', 'general'), space('me', 'personal'), space('checkout')],
            'me',
            'personal',
        ],
        [
            'never falls back to a shared space without a personal one',
            [space('general', 'general'), space('checkout')],
            undefined,
            null,
        ],
    ])('%s', (_, spaces, expectedId, expectedSource) => {
        const { space: chosen, source } = newSessionSpace(spaces)
        expect({ id: chosen?.id, source }).toEqual({ id: expectedId, source: expectedSource })
    })
})
