import { FilterLogicalOperator, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    GroupingModeEnumApi,
    MeasureEnumApi,
    PlatformAlertConfigurationApi,
    TracesAlertThresholdOperatorApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import {
    TracesAlertFormType,
    buildFormDefaults,
    indicatorState,
    snoozeUntilError,
    toWritePayload,
    validateForm,
} from './tracesAlertUtils'

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

    it('keeps a saved grouping the form can only approximate when an edit leaves grouping alone', () => {
        const byOperation = { mode: GroupingModeEnumApi.ByResultLabels, keys: ['name'], max_instances: 50 }
        const saved = {
            ...savedAlert(toWritePayload(form({ serviceNames: ['checkout'] }))),
            grouping: byOperation,
        } as PlatformAlertConfigurationApi

        const edit = { ...buildFormDefaults(saved), name: 'Renamed' }

        expect(toWritePayload(edit, saved).grouping).toEqual(byOperation)
    })

    it('keeps filters that sit in a later group of the saved filter tree', () => {
        const filterGroup = {
            type: FilterLogicalOperator.And,
            values: [
                { type: FilterLogicalOperator.And, values: [] },
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        { key: 'http.route', value: '/cart', operator: PropertyOperator.Exact, type: 'span_attribute' },
                    ],
                },
            ],
        } as unknown as UniversalFiltersGroup

        expect(toWritePayload(form({ filterGroup })).source_config.filters?.filterGroup).toEqual(filterGroup)
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
        ['more checks than the API allows', form({ evaluationPeriods: 11 }), 'evaluationPeriods'],
        ['a fractional check count', form({ evaluationPeriods: 2.5 }), 'evaluationPeriods'],
        ['a negative cooldown', form({ cooldownMinutes: -5 }), 'cooldownMinutes'],
    ])('refuses %s, which the API would reject', (_, invalid, field) => {
        expect(Object.keys(validateForm(invalid))).toEqual([field])
    })

    it.each([
        ['an active snooze shows as snoozed', { snooze_until: '2099-01-01T00:00:00Z' }, 'snoozed'],
        ['a snooze that ran out shows the groups', { snooze_until: '2000-01-01T00:00:00Z' }, 'not_firing'],
        [
            'a broken check outranks a snooze',
            { snooze_until: '2099-01-01T00:00:00Z', check_status: 'broken' },
            'broken',
        ],
    ])('%s', (_, fields, expected) => {
        const alert = { enabled: true, alerts: [], check_status: 'ok', ...fields }
        expect(indicatorState(alert as unknown as PlatformAlertConfigurationApi)).toBe(expected)
    })

    it.each([
        ['in the past', '2026-01-01T11:00:00Z', 'future'],
        ['more than 30 days away', '2026-02-15T12:00:00Z', '30 days'],
        ['tomorrow', '2026-01-02T12:00:00Z', null],
    ])('checks a snooze %s against the API bounds', (_, until, expected) => {
        const error = snoozeUntilError(until, new Date('2026-01-01T12:00:00Z'))
        expect(error ?? null).toEqual(expected ? expect.stringContaining(expected) : null)
    })
})
