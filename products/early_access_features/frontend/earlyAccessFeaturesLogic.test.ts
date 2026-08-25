import { MOCK_TEAM_ID } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, FeatureFlagBasicType } from '~/types'

import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

const FEATURE_FLAG: FeatureFlagBasicType = {
    id: 1,
    team_id: MOCK_TEAM_ID,
    key: 'my-flag',
    name: '',
    filters: { groups: [] },
    deleted: false,
    active: true,
    ensure_experience_continuity: null,
}

const mockFeature = (overrides: Partial<EarlyAccessFeatureType> = {}): EarlyAccessFeatureType => ({
    id: 'abc-123',
    feature_flag: FEATURE_FLAG,
    name: 'My feature',
    description: '',
    stage: EarlyAccessFeatureStage.Concept,
    documentation_url: '',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
})

// Guards the list scene's two mutations of server state: the chained waitlist-count fetch (wrong
// survey_ids, a dropped chain, or a survey failure flagged so the cell shows a dash not a fake 0)
// and the inline assignee PATCH (wrong body/route, and that a failure reverts only the edited row
// without a full-list reload that would clobber a concurrent edit).
describe('earlyAccessFeaturesLogic', () => {
    let logic: ReturnType<typeof earlyAccessFeaturesLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads waitlist response counts for features that have a waitlist survey', async () => {
        let responsesCountUrl: string | null = null
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': {
                    count: 2,
                    results: [
                        mockFeature({ id: 'feature-1', payload: { survey_id: 'survey-1' } }),
                        mockFeature({ id: 'feature-2', stage: EarlyAccessFeatureStage.Beta }),
                    ],
                },
                '/api/projects/:team_id/surveys/responses_count': ({ request }) => {
                    responsesCountUrl = request.url
                    return [200, { 'survey-1': 42 }]
                },
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions([
            'loadEarlyAccessFeaturesSuccess',
            'loadWaitlistResponsesCountSuccess',
        ])

        // Only the feature with a waitlist survey contributes an id
        expect(new URL(responsesCountUrl!).searchParams.get('survey_ids')).toEqual('survey-1')
        expect(logic.values.waitlistResponsesCount).toEqual({ 'survey-1': 42 })
    })

    it('skips the responses count request when no feature has a waitlist survey', async () => {
        let responsesCountCalled = false
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': {
                    count: 1,
                    results: [mockFeature({ stage: EarlyAccessFeatureStage.Beta })],
                },
                '/api/projects/:team_id/surveys/responses_count': () => {
                    responsesCountCalled = true
                    return [200, {}]
                },
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeaturesSuccess']).toFinishAllListeners()

        expect(responsesCountCalled).toBe(false)
    })

    it('flags the failure and keeps an empty counts map when the responses count request fails', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': {
                    count: 1,
                    results: [mockFeature({ payload: { survey_id: 'survey-1' } })],
                },
                '/api/projects/:team_id/surveys/responses_count': () => [500, {}],
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()

        // Fails soft: users without survey access still get a working features list, but the cell
        // shows a dash rather than a fabricated 0
        await expectLogic(logic).toDispatchActions([
            'loadEarlyAccessFeaturesSuccess',
            'loadWaitlistResponsesCountFailure',
        ])

        expect(logic.values.waitlistResponsesCount).toEqual({})
        expect(logic.values.waitlistResponsesCountFailed).toBe(true)
    })

    it('updates the assignee optimistically, PATCHes it, and does not reload the list', async () => {
        let listRequests = 0
        let patchedId: string | null = null
        let patchBody: any = null
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': () => {
                    listRequests++
                    return [
                        200,
                        {
                            count: 1,
                            results: [mockFeature({ id: 'feature-1', stage: EarlyAccessFeatureStage.Beta })],
                        },
                    ]
                },
            },
            patch: {
                '/api/projects/:team_id/early_access_feature/:id': async ({ request, params }) => {
                    patchedId = params.id as string
                    patchBody = await request.json()
                    return [200, mockFeature({ id: 'feature-1', assignee: patchBody.assignee })]
                },
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeaturesSuccess'])

        logic.actions.updateFeatureAssignee('feature-1', { type: 'user', id: 7 })
        // The optimistic write applies synchronously, before the request resolves
        expect(logic.values.earlyAccessFeatures[0].assignee).toEqual({ type: 'user', id: 7 })

        await expectLogic(logic).toFinishAllListeners()
        expect(patchedId).toEqual('feature-1')
        expect(patchBody).toEqual({ assignee: { type: 'user', id: 7 } })
        // A successful edit must not refetch the list
        expect(listRequests).toBe(1)
    })

    it('reverts only the edited row when the assignee update fails', async () => {
        let listRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': () => {
                    listRequests++
                    return [
                        200,
                        {
                            count: 1,
                            results: [
                                mockFeature({ id: 'feature-1', stage: EarlyAccessFeatureStage.Beta, assignee: null }),
                            ],
                        },
                    ]
                },
            },
            patch: {
                '/api/projects/:team_id/early_access_feature/:id': () => [500, {}],
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeaturesSuccess'])

        logic.actions.updateFeatureAssignee('feature-1', { type: 'user', id: 7 })
        // Optimistic write lands first
        expect(logic.values.earlyAccessFeatures[0].assignee).toEqual({ type: 'user', id: 7 })

        await expectLogic(logic).toFinishAllListeners()
        // Then reverts to the previous value for just this row — no full-list reload
        expect(logic.values.earlyAccessFeatures[0].assignee).toBeNull()
        expect(listRequests).toBe(1)
    })
})
