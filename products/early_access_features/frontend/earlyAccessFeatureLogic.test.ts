import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, FeatureFlagBasicType, FeatureFlagType, Region } from '~/types'

import {
    POSTHOG_TEAM_ID,
    earlyAccessFeatureLogic,
    getEarlyAccessFeatureFlagDisabledReason,
} from './earlyAccessFeatureLogic'
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

    // PostHog's own project (US cloud, id 2) requires a description on newly created features.
    // These guard that the frontend validator matches the backend's create-only + US-cloud scope.
    describe('description requirement', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/early_access_feature/:id': mockFeature({ id: 'existing-id' }),
                },
            })
        })

        async function mountWith(id: string, teamId: number, region: Region): Promise<void> {
            logic = earlyAccessFeatureLogic({ id })
            logic.mount()
            // Wait for the mounted loaders (including preflightLogic's own fetch of the default
            // US-region fixture) to settle first, so they can't overwrite the state set below.
            await expectLogic(logic).toFinishAllListeners()
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
            preflightLogic.actions.loadPreflightSuccess({ region } as any)
        }

        it('requires a description when creating on US-cloud project 2', async () => {
            await mountWith('new', POSTHOG_TEAM_ID, Region.US)
            logic.actions.setEarlyAccessFeatureValue('name', 'My feature')
            logic.actions.setEarlyAccessFeatureValue('description', '   ')

            expect(logic.values.earlyAccessFeatureValidationErrors.description).toEqual('A description is required')
        })

        it('accepts a valid description when creating on US-cloud project 2', async () => {
            await mountWith('new', POSTHOG_TEAM_ID, Region.US)
            logic.actions.setEarlyAccessFeatureValue('name', 'My feature')
            logic.actions.setEarlyAccessFeatureValue('description', 'A real description')

            expect(logic.values.earlyAccessFeatureValidationErrors.description).toBeUndefined()
        })

        it('does not require a description for other teams on US cloud', async () => {
            await mountWith('new', MOCK_TEAM_ID, Region.US)
            logic.actions.setEarlyAccessFeatureValue('name', 'My feature')
            logic.actions.setEarlyAccessFeatureValue('description', '')

            expect(logic.values.earlyAccessFeatureValidationErrors.description).toBeUndefined()
        })

        it('does not require a description for project 2 outside US cloud', async () => {
            await mountWith('new', POSTHOG_TEAM_ID, Region.EU)
            logic.actions.setEarlyAccessFeatureValue('name', 'My feature')
            logic.actions.setEarlyAccessFeatureValue('description', '')

            expect(logic.values.earlyAccessFeatureValidationErrors.description).toBeUndefined()
        })

        it('does not block editing an existing description-less feature on US-cloud project 2', async () => {
            await mountWith('existing-id', POSTHOG_TEAM_ID, Region.US)
            logic.actions.setEarlyAccessFeatureValue('description', '')

            expect(logic.values.earlyAccessFeatureValidationErrors.description).toBeUndefined()
        })
    })

    // The picker must gray out exactly the flags the create serializer rejects at link time, so the
    // reason mirrors those three branches. A drift here re-offers a flag the save always refuses.
    describe('getEarlyAccessFeatureFlagDisabledReason', () => {
        const flag = (overrides: Partial<FeatureFlagType>): FeatureFlagType =>
            ({ filters: { groups: [] }, features: [], ...overrides }) as FeatureFlagType

        it('disables a flag that already has a feature attached', () => {
            expect(getEarlyAccessFeatureFlagDisabledReason(flag({ features: [{ id: 1 } as any] }))).toBe(
                'This flag is already linked to another feature.'
            )
        })

        it('disables a group-based flag', () => {
            expect(
                getEarlyAccessFeatureFlagDisabledReason(
                    flag({ filters: { groups: [], aggregation_group_type_index: 0 } })
                )
            ).toBe("Group-based flags can't be linked to an early access feature.")
        })

        it('disables a multivariate flag', () => {
            expect(
                getEarlyAccessFeatureFlagDisabledReason(
                    flag({ filters: { groups: [], multivariate: { variants: [{ key: 'a' } as any] } } })
                )
            ).toBe("Multivariate flags can't be linked to an early access feature.")
        })

        it('leaves a plain boolean flag selectable', () => {
            expect(getEarlyAccessFeatureFlagDisabledReason(flag({}))).toBeNull()
        })
    })

    // A field-scoped rejection (e.g. an unlinkable flag) must render next to the field, not vanish
    // into a toast the user has to correlate — so its `attr` becomes a manual form error.
    it('renders a field-scoped save error inline on that field', () => {
        logic = earlyAccessFeatureLogic({ id: 'new' })
        logic.mount()

        logic.actions.saveEarlyAccessFeatureFailure('Some message', {
            attr: 'feature_flag_id',
            detail: 'Group-based feature flags are not supported for Early Access Features.',
        })

        expect(logic.values.earlyAccessFeatureManualErrors.feature_flag_id).toBe(
            'Group-based feature flags are not supported for Early Access Features.'
        )
    })
})
