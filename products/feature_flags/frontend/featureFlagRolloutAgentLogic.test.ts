import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagRolloutAgentLogic, parseRolloutPercentages } from './featureFlagRolloutAgentLogic'

const FLAG_ID = 1
const PLAN = { id: 'plan-1', feature_flag: FLAG_ID, status: 'active', percentages: [5, 50], steps_applied: 1 }

describe('featureFlagRolloutAgentLogic', () => {
    let listed: jest.Mock
    let created: jest.Mock
    let stopped: jest.Mock

    const mountLogic = (enabled: boolean): ReturnType<typeof featureFlagRolloutAgentLogic.build> => {
        featureFlagLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.FEATURE_FLAG_ROLLOUT_AGENT] : [],
            enabled ? { [FEATURE_FLAGS.FEATURE_FLAG_ROLLOUT_AGENT]: true } : {}
        )
        const logic = featureFlagRolloutAgentLogic({ id: FLAG_ID })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        listed = jest.fn(() => [200, [PLAN]])
        created = jest.fn(() => [201, PLAN])
        stopped = jest.fn(() => [200, { ...PLAN, status: 'stopped' }])
        useMocks({
            get: { '/api/projects/:team_id/feature_flag_rollout_plans/': listed },
            post: {
                '/api/projects/:team_id/feature_flag_rollout_plans/': created,
                '/api/projects/:team_id/feature_flag_rollout_plans/:id/stop/': stopped,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    it.each([
        ['5, 25, 100', [5, 25, 100]],
        ['100', [100]],
        ['25, 5', null],
        ['5, 5', null],
        ['0, 5', null],
        ['5, 101', null],
        ['5, ', null],
        ['1.5, 5', null],
        ['', null],
    ])('parses %j', (text, expected) => {
        expect(parseRolloutPercentages(text)).toEqual(expected)
    })

    it('asks the API for nothing when the feature is off', async () => {
        const logic = mountLogic(false)

        await expectLogic(logic).toMatchValues({ isAgentRolloutAvailable: false, activePlan: null })
        expect(listed).not.toHaveBeenCalled()
    })

    it('shows the active plan and drops it after a stop', async () => {
        const logic = mountLogic(true)

        await expectLogic(logic).toDispatchActions(['loadPlansSuccess']).toMatchValues({ activePlan: PLAN })

        logic.actions.stopPlan(PLAN.id)

        await expectLogic(logic).toDispatchActions(['stopPlanSuccess']).toMatchValues({ activePlan: null })
    })

    it('sends the parsed plan and closes the modal', async () => {
        listed.mockImplementation(() => [200, []])
        const logic = mountLogic(true)
        await expectLogic(logic).toDispatchActions(['loadPlansSuccess'])
        logic.actions.openSetupModal()
        logic.actions.setSetupValues({ percentages: '5, 50', soakHours: 12, healthChecks: 'Errors stay under 2%.' })

        logic.actions.submitSetup()
        await expectLogic(logic).toDispatchActions(['submitSetupSuccess']).toMatchValues({
            isSetupModalOpen: false,
            activePlan: PLAN,
        })

        const { request } = created.mock.calls[0][0]
        expect(await request.clone().json()).toEqual({
            feature_flag: FLAG_ID,
            condition_index: 0,
            percentages: [5, 50],
            soak_hours: 12,
            health_checks: 'Errors stay under 2%.',
        })
    })

    it('does not submit percentages that cannot be applied', async () => {
        listed.mockImplementation(() => [200, []])
        const logic = mountLogic(true)
        logic.actions.setSetupValues({ percentages: '50, 5', healthChecks: 'Errors stay under 2%.' })

        logic.actions.submitSetup()
        await expectLogic(logic).toDispatchActions(['submitSetupFailure'])

        expect(created).not.toHaveBeenCalled()
    })
})
