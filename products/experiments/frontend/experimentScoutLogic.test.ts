import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'
import type { Experiment } from '~/types'

import {
    getExperimentScoutInitialValues,
    isExperimentScoutFlowEnabled,
    experimentScoutLogic,
} from './experimentScoutLogic'

describe('experimentScoutLogic', () => {
    const experimentId = 123
    let logic: ReturnType<typeof experimentScoutLogic.build>
    let sourceLogic: ReturnType<typeof experimentLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
                '/api/projects/:team_id/signals/scout/metadata/current/': () => [
                    200,
                    { enrolled: true, banner_message: null, limits: {} },
                ],
                '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
                '/api/projects/:team_id/signals/source_configs/': () => [200, { count: 0, results: [] }],
            },
        })
        initKeaTests()
        sourceLogic = experimentLogic({ experimentId })
        sourceLogic.mount()
        logic = experimentScoutLogic({ experimentId })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        sourceLogic.unmount()
    })

    it('shows the launch confirmation before opening Self-driving setup', () => {
        sourceLogic.actions.launchExperimentSuccess({ id: experimentId } as Experiment)

        expectLogic(logic).toMatchValues({
            experimentScoutModalStep: 'launch-success',
            scoutInitialValues: expect.objectContaining({
                name: 'signals-scout-experiment-123',
                config: { tags: ['experiments', 'experiment-123'] },
            }),
        })

        logic.actions.continueFromLaunch()

        expectLogic(logic).toMatchValues({ experimentScoutModalStep: 'self-driving-setup' })
    })

    it('skips enablement when Self-driving and its prerequisites are ready', () => {
        integrationsLogic.actions.loadIntegrationsSuccess([
            {
                id: 7,
                kind: 'github',
                display_name: 'example-org',
                config: {},
                created_at: '2026-08-12T00:00:00Z',
                icon_url: '',
            },
        ])
        logic.actions.loadExperimentScoutSetupStatusSuccess({ enrolled: true, selfDrivingEnabled: true })
        sourceLogic.actions.launchExperimentSuccess({ id: experimentId } as Experiment)

        logic.actions.continueFromLaunch()

        expectLogic(logic).toMatchValues({ experimentScoutModalStep: 'scout-setup' })
    })

    it('restores the offer after GitHub setup and removes callback parameters when closed', () => {
        router.actions.push('/experiments/123', {
            createScout: 'experiment',
            integration_id: '7',
            installation_id: '8',
            preserved: 'yes',
        })

        expectLogic(logic).toMatchValues({ experimentScoutModalStep: 'scout-setup' })

        logic.actions.closeExperimentScoutModal()

        expect(router.values.searchParams).toEqual({ preserved: 'yes' })
        expect(logic.values.experimentScoutModalStep).toBeNull()
    })

    it('returns to Self-driving setup after connecting GitHub', () => {
        router.actions.push('/experiments/123', {
            createScout: 'experiment-self-driving',
            integration_id: '7',
        })

        expectLogic(logic).toMatchValues({ experimentScoutModalStep: 'self-driving-setup' })
    })

    it('requires the master experiment and Product autonomy flags', () => {
        expect(isExperimentScoutFlowEnabled({})).toBe(false)
        expect(
            isExperimentScoutFlowEnabled({
                [FEATURE_FLAGS.EXPERIMENT_LAUNCH_SCOUT_FLOW]: 'control',
                [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            })
        ).toBe(false)
        expect(
            isExperimentScoutFlowEnabled({
                [FEATURE_FLAGS.EXPERIMENT_LAUNCH_SCOUT_FLOW]: 'test',
                [FEATURE_FLAGS.PRODUCT_AUTONOMY]: false,
            })
        ).toBe(false)
        expect(
            isExperimentScoutFlowEnabled({
                [FEATURE_FLAGS.EXPERIMENT_LAUNCH_SCOUT_FLOW]: 'test',
                [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            })
        ).toBe(true)
    })

    it('builds stable instructions from the experiment id', () => {
        const initialValues = getExperimentScoutInitialValues(experimentId)

        expect(initialValues.description).toContain('experiment 123')
        expect(initialValues.body).toContain('Analyze PostHog experiment ID 123 on every run.')
        expect(initialValues.body).toContain('Do not report expected variance')
    })
})
