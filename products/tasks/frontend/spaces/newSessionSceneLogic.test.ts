import { expectLogic } from 'kea-test-utils'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceSource, newSessionSceneLogic, newSessionSpace } from './newSessionSceneLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole }) as ChannelDTOApi

const SPACES = [space('general', 'general'), space('me', 'personal'), space('checkout')]

describe('newSessionSceneLogic', () => {
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

    describe('sessionStarted', () => {
        it.each<[string, ChannelDTOApi[], boolean]>([
            ['reloads spaces when the session had no space', [], true],
            ['keeps the spaces when the session had one', [space('me', 'personal')], false],
        ])('%s', async (_, spaces, reloads) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/task_channels/': spaces,
                    '/api/projects/:team_id/task_activity/': { results: [] },
                    '/api/projects/:team_id/tasks/': { results: [], count: 0 },
                },
            })
            initKeaTests()
            const logic = newSessionSceneLogic()
            logic.mount()
            await expectLogic(todaySpacesLogic).toDispatchActions(['loadSpacesSuccess'])

            const expectation = expectLogic(logic, () => logic.actions.sessionStarted('session-1'))
            await (reloads
                ? expectation.toDispatchActions(['loadSpaces'])
                : expectation.toNotHaveDispatchedActions(['loadSpaces']))
        })
    })
})
