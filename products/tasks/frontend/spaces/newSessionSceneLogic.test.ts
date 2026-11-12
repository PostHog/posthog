import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceSource, newSessionSceneLogic, newSessionSpace } from './newSessionSceneLogic'
import { newSessionSuggestionsLogic } from './newSessionSuggestionsLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole }) as ChannelDTOApi

const SPACES = [space('general', 'general'), space('me', 'personal'), space('checkout')]

describe('newSessionSceneLogic', () => {
    describe('newSessionSpace', () => {
        it.each<[string, string | null, string, NewSessionSpaceSource]>([
            ['a space’s own New session uses that space', 'checkout', 'checkout', 'route'],
            ['a generic New session uses personal', null, 'me', 'personal'],
            ['a deleted route space falls back to personal', 'gone', 'me', 'personal'],
        ])('%s', (_, routeSpaceId, expectedId, expectedSource) => {
            const { space: chosen, source } = newSessionSpace(SPACES, routeSpaceId)
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

        it.each([false, true])('attributes the submitted suggestion when selection changes: %s', async (changes) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/task_channels/': SPACES,
                    '/api/projects/:team_id/task_activity/': { results: [] },
                    '/api/projects/:team_id/tasks/': { results: [], count: 0 },
                },
            })
            initKeaTests()
            const logic = newSessionSceneLogic()
            logic.mount()
            await expectLogic(todaySpacesLogic).toDispatchActions(['loadSpacesSuccess'])
            const suggestions = newSessionSuggestionsLogic()
            const [first, second] = suggestions.values.suggestions
            suggestions.actions.selectSuggestion(first, 0)
            const submittedSuggestionId = suggestions.values.selectedSuggestionId
            if (changes) {
                suggestions.actions.selectSuggestion(second, 1)
            }
            const capture = jest.spyOn(posthog, 'capture')

            logic.actions.sessionStarted('session-1', submittedSuggestionId)

            expect(capture).toHaveBeenCalledWith(
                'today new session started',
                expect.objectContaining({ suggestion_id: first.id })
            )
            expect(suggestions.values.selectedSuggestionId).toBe(changes ? second.id : null)
            capture.mockRestore()
        })
    })
})
