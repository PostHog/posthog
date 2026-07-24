import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, FeatureFlagBasicType } from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
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
    stage: EarlyAccessFeatureStage.Draft,
    documentation_url: '',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
})

// Covers the create -> save-as-draft -> edit -> delete UI wiring the deleted early-access
// Playwright spec used to guard. The regressions are real: a save that silently POSTs nothing
// (or to the wrong endpoint), an Edit toggle that never reaches Save, or a delete that leaves the
// feature in the list and the user stranded on a dead detail page. These assert the observable
// results — the request body, the mode flag the Edit/Save button reads, and the navigation — not
// the choreography that produces them.
describe('earlyAccessFeatureLogic', () => {
    let logic: ReturnType<typeof earlyAccessFeatureLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('saves a new feature as draft and navigates to it', async () => {
        let createBody: any = null
        useMocks({
            post: {
                '/api/projects/:team_id/early_access_feature': async ({ request }) => {
                    createBody = await request.json()
                    return [201, mockFeature({ id: 'created-id', name: createBody.name })]
                },
            },
        })

        logic = earlyAccessFeatureLogic({ id: 'new' })
        logic.mount()
        logic.actions.setEarlyAccessFeatureValue('name', 'My new feature')

        await expectLogic(logic, () => {
            logic.actions.submitEarlyAccessFeature()
        }).toDispatchActions(['saveEarlyAccessFeature', 'saveEarlyAccessFeatureSuccess'])

        // Draft is the default stage — this is the "save as draft" path.
        expect(createBody).toMatchObject({
            name: 'My new feature',
            stage: EarlyAccessFeatureStage.Draft,
            _create_in_folder: 'Unfiled/Early Access Features',
        })
        expect(router.values.location.pathname).toMatch(/\/early_access_features\/created-id$/)
    })

    it('toggles edit mode and updates an existing feature', async () => {
        let updateBody: any = null
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature/:id': mockFeature(),
            },
            patch: {
                '/api/projects/:team_id/early_access_feature/:id': async ({ request }) => {
                    updateBody = await request.json()
                    return [200, mockFeature({ name: updateBody.name })]
                },
            },
        })

        logic = earlyAccessFeatureLogic({ id: 'abc-123' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeatureSuccess'])

        expect(logic.values.isEditingFeature).toBe(false)
        logic.actions.editFeature(true)
        expect(logic.values.isEditingFeature).toBe(true)

        logic.actions.setEarlyAccessFeatureValue('name', 'Renamed feature')
        await expectLogic(logic, () => {
            logic.actions.submitEarlyAccessFeature()
        }).toDispatchActions(['saveEarlyAccessFeature', 'saveEarlyAccessFeatureSuccess'])

        expect(updateBody).toMatchObject({ name: 'Renamed feature' })
        // A successful save drops the scene back out of edit mode.
        expect(logic.values.isEditingFeature).toBe(false)
    })

    it('deletes a feature, removes it from the list, and returns to the list page', async () => {
        let deleted = false
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature/:id': mockFeature(),
            },
            delete: {
                '/api/projects/:team_id/early_access_feature/:id': () => {
                    deleted = true
                    return [204, {}]
                },
            },
        })

        earlyAccessFeaturesLogic.mount()
        earlyAccessFeaturesLogic.actions.loadEarlyAccessFeaturesSuccess([mockFeature()])

        logic = earlyAccessFeatureLogic({ id: 'abc-123' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEarlyAccessFeatureSuccess'])

        await expectLogic(logic, () => {
            logic.actions.deleteEarlyAccessFeature('abc-123')
        }).toFinishAllListeners()

        expect(deleted).toBe(true)
        expect(earlyAccessFeaturesLogic.values.earlyAccessFeatures).toEqual([])
        expect(router.values.location.pathname).toMatch(/\/early_access_features$/)
    })
})
