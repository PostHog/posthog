import { expectLogic } from 'kea-test-utils'

import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Region } from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'

const POSTHOG_TEAM_ID = 2

describe('earlyAccessFeatureLogic description requirement', () => {
    let logic: ReturnType<typeof earlyAccessFeatureLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/early_access_feature/': { count: 0, results: [] },
                '/api/projects/:team_id/early_access_feature/:id/': {
                    id: 'existing-id',
                    name: 'Existing feature',
                    description: '',
                    stage: 'concept',
                    feature_flag: { id: 1, key: 'existing', filters: {} },
                    documentation_url: '',
                    payload: {},
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountWith(id: string, teamId: number, region: Region): Promise<void> {
        logic = earlyAccessFeatureLogic({ id })
        logic.mount()
        // Set the connected context before touching the form so the errors selector recomputes with it.
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
        preflightLogic.actions.loadPreflightSuccess({ region } as any)
        await expectLogic(logic).toFinishAllListeners()
    }

    it('requires a description when creating on US-cloud project 2', async () => {
        await mountWith('new', POSTHOG_TEAM_ID, Region.US)
        logic.actions.setEarlyAccessFeatureValue('name', 'My feature')
        logic.actions.setEarlyAccessFeatureValue('description', '   ')

        expect(logic.values.earlyAccessFeatureValidationErrors.description).toEqual('A description is required')
    })

    it('does not require a description for other teams on US cloud', async () => {
        await mountWith('new', 997, Region.US)
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
