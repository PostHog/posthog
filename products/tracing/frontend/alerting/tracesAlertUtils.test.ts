import {
    GroupingModeEnumApi,
    MeasureEnumApi,
    PlatformAlertConfigurationApi,
    TracesAlertThresholdOperatorApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { TracesAlertFormType, buildFormDefaults, toWritePayload, validateForm } from './tracesAlertUtils'

function savedAlert(payload: ReturnType<typeof toWritePayload>): PlatformAlertConfigurationApi {
    return {
        ...payload,
        id: 'alert-1',
        grouping: { ...payload.grouping, max_instances: 50 },
    } as unknown as PlatformAlertConfigurationApi
}

function form(overrides: Partial<TracesAlertFormType>): TracesAlertFormType {
    return { ...buildFormDefaults(null), name: 'Checkout', threshold: 5, ...overrides }
}

describe('tracesAlertUtils', () => {
    it.each([
        ['error rate as a percentage', form({ measure: MeasureEnumApi.ErrorRate, threshold: 7 }), 0.07],
        ['latency in milliseconds', form({ measure: MeasureEnumApi.Latency, percentile: 99, threshold: 750 }), 750],
        ['a request count', form({ measure: MeasureEnumApi.RequestCount, threshold: 100 }), 100],
    ])('saves %s and reads it back unchanged', (_, original, storedThreshold) => {
        const payload = toWritePayload(original)
        expect(payload.source_config.condition.threshold).toBe(storedThreshold)
        expect(buildFormDefaults(savedAlert(payload))).toEqual(original)
    })

    it('keeps a saved group limit when an edit keeps the alert grouped', () => {
        const grouped = form({ groupBy: 'service' })
        const saved = savedAlert(toWritePayload(grouped))

        expect(toWritePayload(grouped, saved).grouping).toEqual({
            mode: GroupingModeEnumApi.ByResultLabels,
            keys: ['service_name'],
            max_instances: 50,
        })
    })

    it.each([
        ['an error rate over 100%', form({ measure: MeasureEnumApi.ErrorRate, threshold: 150 }), 'threshold'],
        [
            'a grouped alert below a threshold',
            form({ groupBy: 'service', thresholdOperator: TracesAlertThresholdOperatorApi.Below }),
            'groupBy',
        ],
        ['grouping by operation with no service', form({ groupBy: 'service_and_operation' }), 'groupBy'],
        ['more matching checks than checks', form({ datapointsToAlarm: 3, evaluationPeriods: 2 }), 'datapointsToAlarm'],
    ])('refuses %s, which the API would reject', (_, invalid, field) => {
        expect(Object.keys(validateForm(invalid))).toEqual([field])
    })
})
