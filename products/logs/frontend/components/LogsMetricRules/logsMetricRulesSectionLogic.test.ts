import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsMetricRulesSectionLogic } from './logsMetricRulesSectionLogic'

// Keep the real retry policy, but without the backoff waits that would put these tests over the 5s limit.
jest.mock('lib/utils/async', () => {
    const actual = jest.requireActual('lib/utils/async')
    return {
        ...actual,
        retryWithBackoff: (fn: () => Promise<unknown>, options: Record<string, unknown>) =>
            actual.retryWithBackoff(fn, { ...options, initialDelayMs: 0 }),
    }
})

const FLAG_GATED_403: [number, Record<string, string>] = [
    403,
    {
        type: 'authentication_error',
        code: 'feature_flag_required',
        detail: "This action requires feature flag 'metrics' to be enabled for your organization.",
    },
]

describe('logsMetricRulesSectionLogic', () => {
    let logic: ReturnType<typeof logsMetricRulesSectionLogic.build>
    let listResponses: [number, Record<string, any>][]
    let listCalls: number

    function mountWithListResponses(...responses: [number, Record<string, any>][]): void {
        listResponses = responses
        logic = logsMetricRulesSectionLogic()
        logic.mount()
    }

    beforeEach(() => {
        listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/logs/metric_rules/': () =>
                    listResponses[Math.min(listCalls++, listResponses.length - 1)],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The browser evaluates the metrics flag as on as soon as the user enrolls in the preview,
    // but the server only sees the enrollment once the person property is ingested.
    it('retries a flag-gated 403 and loads the rules once the server sees the enrollment', async () => {
        mountWithListResponses(FLAG_GATED_403, [200, { results: [{ id: 'rule-1' }] }])

        await expectLogic(logic)
            .toDispatchActions(['loadRulesSuccess'])
            .toNotHaveDispatchedActions(['loadRulesFailure'])

        expect(listCalls).toBe(2)
        expect(logic.values.rules).toEqual([{ id: 'rule-1' }])
    })

    it('settles on an empty list without a failure when the flag gate stays closed', async () => {
        mountWithListResponses(FLAG_GATED_403)

        await expectLogic(logic)
            .toDispatchActions(['loadRulesSuccess'])
            .toNotHaveDispatchedActions(['loadRulesFailure'])

        expect(logic.values.rules).toEqual([])
    })

    it('fails without retrying on other errors', async () => {
        mountWithListResponses([500, { detail: 'Server error' }])

        await expectLogic(logic).toDispatchActions(['loadRulesFailure'])

        expect(listCalls).toBe(1)
    })
})
