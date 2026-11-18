import { buildFormDefaults, MetricsAlertFormType, toWritePayload, validateForm } from './metricsAlertUtils'

describe('metricsAlertUtils', () => {
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
            form: base,
            expected: {
                condition: { kind: 'threshold', operator: 'gte', threshold: 5 },
                grouping: { mode: 'single' },
            },
        },
        {
            case: 'present, grouped',
            form: { ...base, conditionKind: 'present' as const, groupByLabels: ['service_name'] },
            expected: {
                condition: { kind: 'present' },
                grouping: { mode: 'by_result_labels', keys: ['service_name'] },
            },
        },
        {
            // An edit that leaves the limit out resets it to the default of 100.
            case: 'saved grouping limit kept',
            form: { ...base, groupByLabels: ['service_name'], maxInstances: 10 },
            expected: {
                condition: { kind: 'threshold', operator: 'gte', threshold: 5 },
                grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 10 },
            },
        },
    ])('$case', ({ form, expected }) => {
        const payload = toWritePayload(form)

        expect(payload).toMatchObject({
            name: 'Error rate',
            source_config: { query: 'rate(errors_total[5m])', condition: expected.condition },
            grouping: expected.grouping,
        })
        expect(payload.source_config.condition).toEqual(expected.condition)
    })

    // The platform accepts up to 60 checks for a metrics alert, so the form must too.
    it.each([
        { periods: 60, error: undefined },
        { periods: 61, error: 'Enter a number of checks from 1 to 60.' },
    ])('validateForm on a window of $periods checks', ({ periods, error }) => {
        const errors = validateForm({ ...base, evaluationPeriods: periods, datapointsToAlarm: periods })

        expect(errors.evaluationPeriods).toEqual(error)
        expect(errors.datapointsToAlarm).toEqual(error)
    })
})
