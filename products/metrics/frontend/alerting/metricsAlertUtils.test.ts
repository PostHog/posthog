import { buildFormDefaults, MetricsAlertFormType, toWritePayload } from './metricsAlertUtils'

describe('toWritePayload', () => {
    const base: MetricsAlertFormType = {
        ...buildFormDefaults(null),
        name: ' Error rate ',
        query: ' rate(errors_total[5m]) ',
        operator: 'gte',
        threshold: 5,
    }

    // The API refuses a present condition with an operator or threshold, and a by_result_labels grouping with no keys.
    it.each([
        {
            case: 'threshold, ungrouped',
            form: { ...base, labels: [{ name: ' team ', value: ' apm ' }] },
            expected: {
                condition: { kind: 'threshold', operator: 'gte', threshold: 5 },
                grouping: { mode: 'single' },
                labels: { team: 'apm' },
            },
        },
        {
            case: 'present, grouped',
            form: { ...base, conditionKind: 'present' as const, groupByLabels: ['service_name'] },
            expected: {
                condition: { kind: 'present' },
                grouping: { mode: 'by_result_labels', keys: ['service_name'] },
                labels: {},
            },
        },
    ])('$case', ({ form, expected }) => {
        const payload = toWritePayload(form)

        expect(payload).toMatchObject({
            name: 'Error rate',
            source_config: { query: 'rate(errors_total[5m])', condition: expected.condition },
            grouping: expected.grouping,
            labels: expected.labels,
        })
        expect(payload.source_config.condition).toEqual(expected.condition)
    })
})
