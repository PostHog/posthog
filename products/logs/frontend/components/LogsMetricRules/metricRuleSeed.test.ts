import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildMetricRuleSeedFromLog } from './metricRuleSeed'

// Mirrors METRIC_NAME_PATTERN in products/logs/backend/presentation/views/metric_rules_api.py:
// a seed that fails it would 400 on create, defeating the quick-add flow.
const METRIC_NAME_PATTERN = /^[a-zA-Z][a-zA-Z0-9._-]*$/

function makeLog(
    overrides: Partial<Parameters<typeof buildMetricRuleSeedFromLog>[0]> = {}
): Parameters<typeof buildMetricRuleSeedFromLog>[0] {
    return {
        uuid: 'log-1',
        severity_text: 'error',
        resource_attributes: { 'service.name': 'checkout' },
        ...overrides,
    }
}

describe('buildMetricRuleSeedFromLog', () => {
    it('seeds name, metric name, and filters from the log service and severity', () => {
        const seed = buildMetricRuleSeedFromLog(makeLog())

        expect(seed.seedKey).toEqual('log-1')
        expect(seed.name).toEqual('checkout error logs')
        expect(seed.metric_name).toEqual('log.checkout.error')
        expect(seed.filter_group).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'service_name',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['checkout'],
                },
                {
                    key: 'severity_level',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['error'],
                },
            ],
        })
    })

    it('omits the service filter when the log has no service name', () => {
        const seed = buildMetricRuleSeedFromLog(makeLog({ resource_attributes: {} }))

        expect(seed.name).toEqual('error logs')
        expect(seed.metric_name).toEqual('log.error')
        expect(seed.filter_group.values).toHaveLength(1)
        expect(seed.filter_group.values[0]).toMatchObject({ key: 'severity_level', value: ['error'] })
    })

    test.each(['My Service', '123 service', 'svc/π&', 'a--b__c'])(
        'produces a metric name the backend accepts for service %j',
        (serviceName) => {
            const seed = buildMetricRuleSeedFromLog(makeLog({ resource_attributes: { 'service.name': serviceName } }))

            expect(seed.metric_name).toMatch(METRIC_NAME_PATTERN)
        }
    )
})
