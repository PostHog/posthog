import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { OpportunityApi, OpportunityStatusEnumApi, ProposedExperimentApi } from './generated/api.schemas'
import { opportunitiesLogic, transitionsForStatus } from './opportunitiesLogic'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

const openOpportunity: OpportunityApi = {
    id: 'opp-1',
    kind: 'build',
    status: 'open',
    title: 'Recover the signup drop',
    summary: 's',
    suggested_action: 'a',
    evidence: [{ type: 'insight', ref: 'abc123', label: 'Signups', url: '/insights/abc123' }],
    goal_relevant: false,
    proposed_experiment: null,
    first_seen_brief: 'brief-1',
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

const proposal: ProposedExperimentApi = {
    hypothesis: 'Move the entry point above the fold',
    flag_key_suggestion: 'subscription-entry-point',
    target_metric: { insight_short_id: 'ins-9' },
    variant_sketch: 'Control keeps the sidebar; test adds a button',
}

const proposalOpportunity: OpportunityApi = {
    ...openOpportunity,
    goal_relevant: true,
    proposed_experiment: proposal,
}

describe('opportunitiesLogic', () => {
    let logic: ReturnType<typeof opportunitiesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/opportunities/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PULSE], { [FEATURE_FLAGS.PULSE]: true })
        logic = opportunitiesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each<[string, string[]]>([
        ['open', ['acted', 'dismiss']],
        ['dismissed', ['reopen']],
        ['acted', []],
        ['resolved', []],
    ])('offers the right transitions for a %s opportunity', (status, expected) => {
        expect(transitionsForStatus(status as OpportunityStatusEnumApi).map(({ transition }) => transition)).toEqual(
            expected
        )
    })

    it('swaps in the server row on transition success', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/dismiss/': () => [
                    200,
                    { ...openOpportunity, status: 'dismissed', updated_at: '2026-07-04T00:00:00Z' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionSucceeded'])
            .toMatchValues({ transitionsInFlight: {} })
        expect(logic.values.opportunities[0].status).toEqual('dismissed')
        expect(logic.values.opportunities[0].updated_at).toEqual('2026-07-04T00:00:00Z')
    })

    it('keeps the status unchanged and toasts when a transition fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/reopen/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'invalid',
                        detail: 'This opportunity is open; it must be dismissed to become open.',
                        attr: null,
                    },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'reopen')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionFailed'])
            .toMatchValues({ transitionsInFlight: {} })
        expect(logic.values.opportunities[0].status).toEqual('open')
        expect(errorSpy).toHaveBeenCalledWith('This opportunity is open; it must be dismissed to become open.')
    })

    it('ignores a second transition for the same row while one is in flight', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/dismiss/': () => {
                    requests += 1
                    return [200, { ...openOpportunity, status: 'dismissed' }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
        }).toFinishAllListeners()
        expect(requests).toEqual(1)
    })

    it('flags a failed load so the panel can show an error instead of the empty state', async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: { '/api/projects/:team_id/pulse/opportunities/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.loadOpportunities()
        }).toDispatchActions(['loadOpportunitiesFailure'])
        expect(logic.values.opportunitiesLoadFailed).toBe(true)
        resumeKeaLoadersErrors()
    })

    it.each<[string, ProposedExperimentApi, boolean, string]>([
        [
            'with a target metric',
            proposal,
            true,
            'Hypothesis: Move the entry point above the fold\nFeature flag key: subscription-entry-point\nTarget metric insight: ins-9\nVariants: Control keeps the sidebar; test adds a button',
        ],
        [
            'without a target metric',
            { ...proposal, target_metric: null },
            false,
            'Hypothesis: Move the entry point above the fold\nFeature flag key: subscription-entry-point\nVariants: Control keeps the sidebar; test adds a button',
        ],
    ])(
        'creating an experiment %s marks acted, copies the proposal, then navigates',
        async (_name, prop, hasTargetMetric, expectedText) => {
            ;(copyToClipboard as jest.Mock).mockClear().mockResolvedValue(true)
            const pushSpy = jest.spyOn(router.actions, 'push').mockReturnValue(undefined as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
            pushSpy.mockClear()
            captureSpy.mockClear()
            useMocks({
                post: {
                    '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                        200,
                        { ...proposalOpportunity, proposed_experiment: prop, status: 'acted' },
                    ],
                },
            })
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadOpportunitiesSuccess([{ ...proposalOpportunity, proposed_experiment: prop }])

            await expectLogic(logic, () => {
                logic.actions.createExperimentFromOpportunity('opp-1')
            }).toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionSucceeded'])

            // Acted lands before navigation, so accountability re-scores this opportunity even if
            // the user abandons the experiment form.
            expect(logic.values.opportunities[0].status).toEqual('acted')
            expect(copyToClipboard).toHaveBeenCalledWith(expectedText, 'experiment proposal')
            expect(captureSpy).toHaveBeenCalledWith('pulse_opportunity_experiment_created', {
                opportunity_id: 'opp-1',
                has_target_metric: hasTargetMetric,
                proposal_copied: true,
            })
            expect(pushSpy).toHaveBeenCalledWith(urls.experiment('new'))
        }
    )

    it('never navigates when the acted transition fails', async () => {
        ;(copyToClipboard as jest.Mock).mockClear().mockResolvedValue(true)
        const pushSpy = jest.spyOn(router.actions, 'push').mockReturnValue(undefined as any)
        pushSpy.mockClear()
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [400, { detail: 'nope' }],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([proposalOpportunity])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionFailed'])

        expect(logic.values.opportunities[0].status).toEqual('open')
        expect(copyToClipboard).not.toHaveBeenCalled()
        expect(pushSpy).not.toHaveBeenCalled()
        expect(errorSpy).toHaveBeenCalled()
    })

    it('still navigates but warns when copying the proposal fails', async () => {
        ;(copyToClipboard as jest.Mock).mockClear().mockResolvedValue(false)
        const pushSpy = jest.spyOn(router.actions, 'push').mockReturnValue(undefined as any)
        const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        pushSpy.mockClear()
        captureSpy.mockClear()
        const warningSpy = jest.spyOn(lemonToast, 'warning')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                    200,
                    { ...proposalOpportunity, status: 'acted' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([proposalOpportunity])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toDispatchActions(['opportunityTransitionSucceeded'])

        expect(warningSpy).toHaveBeenCalled()
        expect(captureSpy).toHaveBeenCalledWith('pulse_opportunity_experiment_created', {
            opportunity_id: 'opp-1',
            has_target_metric: true,
            proposal_copied: false,
        })
        expect(pushSpy).toHaveBeenCalledWith(urls.experiment('new'))
    })

    it('is a no-op for an opportunity with no proposal', async () => {
        ;(copyToClipboard as jest.Mock).mockClear().mockResolvedValue(true)
        const pushSpy = jest.spyOn(router.actions, 'push').mockReturnValue(undefined as any)
        pushSpy.mockClear()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity]) // proposed_experiment: null

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toFinishAllListeners()

        expect(logic.values.opportunities[0].status).toEqual('open')
        expect(copyToClipboard).not.toHaveBeenCalled()
        expect(pushSpy).not.toHaveBeenCalled()
    })
})
