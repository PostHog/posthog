import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsMetricRulesList } from 'products/logs/frontend/generated/api'

import { logsUrlForMetricRule, metricsLogsSourceLogic } from './metricsLogsSourceLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    logsMetricRulesList: jest.fn(),
}))

const RULE = {
    id: 'rule-1',
    name: 'API errors',
    metric_name: 'log.api.errors',
    enabled: true,
    filter_group: { type: 'AND', values: [{ type: 'AND', values: [] }] },
    group_by: [],
} as any

describe('metricsLogsSourceLogic', () => {
    let logic: ReturnType<typeof metricsLogsSourceLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(logsMetricRulesList).mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('indexes rules by metric name', async () => {
        jest.mocked(logsMetricRulesList).mockResolvedValue({ results: [RULE] } as any)
        logic = metricsLogsSourceLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadLogsMetricRulesSuccess']).toFinishAllListeners()

        expect(logic.values.ruleByMetricName['log.api.errors']).toMatchObject({ id: 'rule-1' })
        expect(logic.values.ruleByMetricName['log.other']).toBeUndefined()
    })

    it('stays empty when the rules API is unavailable', async () => {
        // The metric rules endpoint is flag-gated server-side; a team without the flag must not
        // see an error toast or a crash in the metrics viewer.
        jest.mocked(logsMetricRulesList).mockRejectedValue(new Error('403'))
        logic = metricsLogsSourceLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadLogsMetricRulesSuccess']).toFinishAllListeners()

        expect(logic.values.ruleByMetricName).toEqual({})
    })

    it('builds a logs deep link carrying the rule filters', () => {
        expect(logsUrlForMetricRule(RULE)).toEqual(
            `/logs?filterGroup=${encodeURIComponent(JSON.stringify(RULE.filter_group))}`
        )
        expect(logsUrlForMetricRule({ ...RULE, filter_group: null })).toEqual('/logs')
    })
})
