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
// survey_ids, a dropped chain, or a survey 403 breaking the whole list) and the inline assignee
// PATCH (wrong body/route, or a failed PATCH leaving the optimistic update in place).
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

    it('keeps an empty counts map when the responses count request fails', async () => {
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

        // Fails soft: users without survey access must still get a working features list
        await expectLogic(logic).toDispatchActions([
            'loadEarlyAccessFeaturesSuccess',
            'loadWaitlistResponsesCountSuccess',
        ])

        expect(logic.values.waitlistResponsesCount).toEqual({})
    })

    it('updates the assignee optimistically and PATCHes it to the right feature', async () => {
        let patchedId: string | null = null
        let patchBody: any = null
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': {
                    count: 1,
                    results: [mockFeature({ id: 'feature-1', stage: EarlyAccessFeatureStage.Beta })],
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
        // Reducer applies before the request resolves
        expect(logic.values.earlyAccessFeatures[0].assignee).toEqual({ type: 'user', id: 7 })

        await expectLogic(logic).toFinishAllListeners()
        expect(patchedId).toEqual('feature-1')
        expect(patchBody).toEqual({ assignee: { type: 'user', id: 7 } })
    })

    it('reloads the list when the assignee update fails', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature': {
                    count: 1,
                    results: [mockFeature({ id: 'feature-1', stage: EarlyAccessFeatureStage.Beta, assignee: null })],
                },
            },
            patch: {
                '/api/projects/:team_id/early_access_feature/:id': () => [500, {}],
            },
        })

        logic = earlyAccessFeaturesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeaturesSuccess'])

        await expectLogic(logic, () => {
            logic.actions.updateFeatureAssignee('feature-1', { type: 'user', id: 7 })
        }).toDispatchActions(['updateFeatureAssignee', 'loadEarlyAccessFeatures', 'loadEarlyAccessFeaturesSuccess'])

        // The optimistic update is reverted to server truth
        expect(logic.values.earlyAccessFeatures[0].assignee).toBeNull()
    })
})
