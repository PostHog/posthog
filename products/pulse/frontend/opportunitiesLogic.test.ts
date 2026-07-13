import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { OpportunityApi, OpportunityStatusEnumApi } from './generated/api.schemas'
import { opportunitiesLogic, transitionsForStatus } from './opportunitiesLogic'

const openOpportunity: OpportunityApi = {
    id: 'opp-1',
    kind: 'build',
    status: 'open',
    title: 'Recover the signup drop',
    summary: 's',
    suggested_action: 'a',
    evidence: [{ type: 'insight', ref: 'abc123', label: 'Signups', url: '/insights/abc123' }],
    first_seen_brief: null,
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
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
})
