import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mergeSplitPersonLogic } from './mergeSplitPersonLogic'
import { personsLogic } from './personsLogic'

const URL_DISTINCT_ID = 'user@example.com'

// Shape that drf-exceptions-hog renders for the `distinct_ids_to_split` ValidationError raised
// by `posthog/api/person.py`
const STALE_DISTINCT_ID_RESPONSE = {
    type: 'validation_error',
    code: 'invalid',
    detail: "not on this person: ['user-456']",
    attr: 'distinct_ids_to_split',
}

const MOCK_PERSON = {
    id: '123',
    uuid: 'abc-123',
    distinct_ids: [URL_DISTINCT_ID, 'user-456'],
    properties: { email: 'user@example.com' },
    created_at: '2024-01-01T00:00:00Z',
}

describe('mergeSplitPersonLogic', () => {
    let logic: ReturnType<typeof mergeSplitPersonLogic.build>
    let personsLogicInstance: ReturnType<typeof personsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/persons/': { results: [MOCK_PERSON], count: 1 },
            },
            post: {
                '/api/person/123/split/': { success: true },
            },
        })
        initKeaTests()
        // A child environment has a project id that differs from its environment id. The default
        // mocks give it the same value for both, which hides a request sent to the wrong scope.
        ApiConfig.setCurrentProjectId(MOCK_TEAM_ID + 1)

        // execute() reports through eventUsageLogic, which must be mounted (in the app it always is)
        eventUsageLogic.mount()

        personsLogicInstance = personsLogic({ syncWithUrl: true, urlId: URL_DISTINCT_ID })
        personsLogicInstance.mount()

        logic = mergeSplitPersonLogic({ person: MOCK_PERSON, urlId: URL_DISTINCT_ID })
        logic.mount()
    })

    afterEach(async () => {
        // Drain in-flight execute() calls before unmounting so their success path
        // doesn't dispatch into an unmounted logic
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        personsLogicInstance.unmount()
        eventUsageLogic.unmount()
    })

    describe('cancel', () => {
        it('closes the modal by dispatching setSplitMergeModalShown(false) on the correct personsLogic instance', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: true,
            })

            await expectLogic(logic, () => {
                logic.actions.cancel()
            })
                .toDispatchActions([personsLogicInstance.actionTypes.setSplitMergeModalShown])
                .toFinishListeners()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: false,
            })
        })

        it('does not close the modal while execute is loading', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            logic.actions.execute()
            logic.actions.cancel()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: true,
            })
        })
    })

    describe('execute', () => {
        it('closes the modal on successful split', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                .toDispatchActions(['execute', 'executeSuccess'])
                .toFinishListeners()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: false,
            })
        })
    })

    describe('partial split', () => {
        it('defaults to the "all" split mode with an empty distinct ID list', async () => {
            await expectLogic(logic).toMatchValues({
                splitMode: 'all',
                distinctIdsToSplit: [],
            })
        })

        it('tracks mode changes and selected distinct IDs', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSplitMode('partial')
                logic.actions.setDistinctIdsToSplit(['user-456'])
            }).toMatchValues({
                splitMode: 'partial',
                distinctIdsToSplit: ['user-456'],
            })
        })

        it('recovers in place when a selected distinct ID has moved off the person', async () => {
            let refreshScopeId: string | undefined
            useMocks({
                get: {
                    '/api/projects/:team_id/persons/123/': ({ params }) => {
                        refreshScopeId = String(params.team_id)
                        return { ...MOCK_PERSON, distinct_ids: [URL_DISTINCT_ID] }
                    },
                },
                post: {
                    '/api/person/123/split/': () => [400, STALE_DISTINCT_ID_RESPONSE],
                },
            })
            personsLogicInstance.actions.setSplitMergeModalShown(true)
            logic.actions.setSplitMode('partial')
            logic.actions.setDistinctIdsToSplit(['user-456'])

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                // executeSuccess, not executeFailure: the generic loader handler would toast the
                // raw backend string and report the validation error to error tracking
                .toDispatchActions(['execute', 'splitRejected'])
                .toDispatchActions(eventUsageLogic, [eventUsageLogic.actionCreators.reportPersonSplitRejected(1)])
                .toDispatchActions(['executeSuccess'])
                .toFinishListeners()

            await expectLogic(logic).toMatchValues({
                staleDistinctIds: ['user-456'],
                distinctIdsToSplit: [],
                person: expect.objectContaining({ distinct_ids: [URL_DISTINCT_ID] }),
            })
            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: true,
            })
            // The persons route is nested under `/api/projects/`, but the path segment it reads is
            // the environment id. A project id there resolves to another environment and 404s, so
            // the modal would fall back to the generic copy and name no stale IDs.
            expect(refreshScopeId).toEqual(String(MOCK_TEAM_ID))
        })

        it.each([
            ['drops a main distinct ID that moved off the person', 'user-456', null],
            ['keeps a main distinct ID that is still on the person', URL_DISTINCT_ID, URL_DISTINCT_ID],
        ])('%s', async (_, mainDistinctId, expected) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/persons/123/': { ...MOCK_PERSON, distinct_ids: [URL_DISTINCT_ID] },
                },
                post: {
                    '/api/person/123/split/': () => [400, STALE_DISTINCT_ID_RESPONSE],
                },
            })
            logic.actions.setSelectedPersonToAssignSplit(mainDistinctId)
            logic.actions.setSplitMode('partial')
            logic.actions.setDistinctIdsToSplit(['user-456'])

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                .toDispatchActions(['execute', 'splitRejected', 'executeSuccess'])
                .toFinishListeners()

            // "all" mode submits this ID as `main_distinct_id`, and the backend splits every
            // distinct ID off the person when no ID on it matches.
            await expectLogic(logic).toMatchValues({ selectedPersonToAssignSplit: expected })
        })

        it('still recovers when the current distinct IDs cannot be loaded', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/persons/123/': () => [500, {}],
                },
                post: {
                    '/api/person/123/split/': () => [400, STALE_DISTINCT_ID_RESPONSE],
                },
            })
            logic.actions.setSplitMode('partial')
            logic.actions.setDistinctIdsToSplit(['user-456'])

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                .toDispatchActions(['execute', 'splitRejected'])
                // Null, not 0: the rejection proves an ID is stale even when the refresh failed
                .toDispatchActions(eventUsageLogic, [eventUsageLogic.actionCreators.reportPersonSplitRejected(null)])
                .toDispatchActions(['executeSuccess'])
                .toFinishListeners()

            await expectLogic(logic).toMatchValues({
                staleDistinctIds: [],
                distinctIdsToSplit: ['user-456'],
            })
        })

        it('executes successfully when partial mode has a selection', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)
            logic.actions.setSplitMode('partial')
            logic.actions.setDistinctIdsToSplit(['user-456'])

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                .toDispatchActions(['execute', 'executeSuccess'])
                .toFinishListeners()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: false,
            })
        })
    })

    describe('urlId matching', () => {
        it('connects to the correct personsLogic instance based on urlId', async () => {
            const differentPersonsLogic = personsLogic({ syncWithUrl: true, urlId: 'different-user' })
            differentPersonsLogic.mount()
            differentPersonsLogic.actions.setSplitMergeModalShown(true)

            logic.actions.cancel()

            await expectLogic(differentPersonsLogic).toMatchValues({
                splitMergeModalShown: true,
            })

            differentPersonsLogic.unmount()
        })
    })
})
