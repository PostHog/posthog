import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsMetricRuleFormLogic } from './logsMetricRuleFormLogic'
import type { LogsMetricRuleSeed } from './metricRuleSeed'

const seedFilterGroup: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            key: 'service_name',
            type: PropertyFilterType.Log,
            operator: PropertyOperator.Exact,
            value: ['checkout'],
        } as never,
    ],
}

const seed: LogsMetricRuleSeed = {
    seedKey: 'log-1',
    name: 'checkout error logs',
    metric_name: 'log.checkout.error',
    filter_group: seedFilterGroup,
}

describe('logsMetricRuleFormLogic', () => {
    let logic: ReturnType<typeof logsMetricRuleFormLogic.build>
    let createdBodies: Record<string, any>[]

    beforeEach(() => {
        createdBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/logs/metric_rules/': { results: [] },
            },
            post: {
                '/api/projects/:team_id/logs/metric_rules/': async ({ request }) => {
                    const body = (await request.clone().json()) as Record<string, any>
                    createdBodies.push(body)
                    return [201, { ...body, id: 'rule-1' }]
                },
            },
        })
        initKeaTests()
        logic = logsMetricRuleFormLogic({ rule: null, seed })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('prefills the form from a seed', () => {
        expect(logic.values.metricRuleForm).toMatchObject({
            name: 'checkout error logs',
            metric_name: 'log.checkout.error',
            filter_group: seedFilterGroup,
        })
    })

    it('a plain submit creates the rule and closes the modals', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitMetricRuleForm()
        })
            .toDispatchActions(['closeRuleModal', 'closeQuickCreateModal', 'submitMetricRuleFormSuccess'])
            .toFinishAllListeners()

        expect(createdBodies).toHaveLength(1)
        expect(createdBodies[0]).toMatchObject({ metric_name: 'log.checkout.error' })
    })

    it('create-and-add-another keeps the modal open and the filters, clearing the identity fields', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitAndAddAnother()
        })
            .toDispatchActions(['submitMetricRuleFormSuccess'])
            .toNotHaveDispatchedActions(['closeRuleModal', 'closeQuickCreateModal'])
            .toFinishAllListeners()

        expect(createdBodies).toHaveLength(1)
        expect(logic.values.metricRuleForm.name).toEqual('')
        expect(logic.values.metricRuleForm.metric_name).toEqual('')
        expect(logic.values.metricRuleForm.filter_group).toEqual(seedFilterGroup)
    })
})
