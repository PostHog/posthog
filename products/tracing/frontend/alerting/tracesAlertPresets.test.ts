import { AggregatedSpanRow } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    MeasureEnumApi,
    TracesAlertThresholdOperatorApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { TracesAlertPreset, buildPresetForm, presetDisabledReason } from './tracesAlertPresets'
import { toWritePayload, validateForm } from './tracesAlertUtils'

const ms = (value: number): number => value * 1_000_000

function row(overrides: Partial<AggregatedSpanRow> = {}): AggregatedSpanRow {
    return {
        service_name: 'checkout-api',
        name: 'POST /cart',
        count: 1000,
        error_count: 40,
        p50_duration_nano: ms(120),
        p95_duration_nano: ms(401),
        p99_duration_nano: ms(800),
        p999_duration_nano: ms(1200),
        total_duration_nano: ms(150_000),
        avg_duration_nano: ms(150),
        ...overrides,
    }
}

const OPERATION_FILTER = {
    type: 'AND',
    values: [
        {
            type: 'AND',
            values: [
                { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: ['POST /cart'] },
            ],
        },
    ],
}

describe('buildPresetForm', () => {
    it.each<[TracesAlertPreset, Partial<AggregatedSpanRow>, object]>([
        [
            'error_rate',
            {},
            { measure: MeasureEnumApi.ErrorRate, threshold: 0.06, threshold_operator: 'above', percentile: null },
        ],
        // An operation without errors still gets a 1% floor, not a 0% threshold every error crosses.
        ['error_rate', { error_count: 0 }, { measure: MeasureEnumApi.ErrorRate, threshold: 0.01 }],
        // The check fires strictly above the threshold, so a 100% threshold would never fire.
        ['error_rate', { error_count: 700 }, { measure: MeasureEnumApi.ErrorRate, threshold: 0.99 }],
        [
            'p95_latency',
            {},
            { measure: MeasureEnumApi.Latency, percentile: 95, threshold: 602, threshold_operator: 'above' },
        ],
        [
            'requests_stopped',
            {},
            {
                measure: MeasureEnumApi.RequestCount,
                threshold: 1,
                threshold_operator: TracesAlertThresholdOperatorApi.Below,
            },
        ],
    ])('saves the %s preset scoped to the row over 5 minutes', (preset, overrides, condition) => {
        const form = buildPresetForm(row(overrides), preset)

        expect(validateForm(form)).toEqual({})
        const payload = toWritePayload(form)
        expect(payload.source_config).toEqual({
            filters: { serviceNames: ['checkout-api'], filterGroup: OPERATION_FILTER },
            condition: expect.objectContaining({ ...condition, window_minutes: 5 }),
        })
        expect(payload.grouping.mode).toBe('single')
    })

    it.each([
        ['ascii', 'x'.repeat(400)],
        // An emoji across the cut must not leave half a surrogate pair behind.
        ['an emoji at the cut', `${'x'.repeat(228)}${'😀'.repeat(20)}`],
    ])('shortens a long operation name with %s to the API limit and keeps the condition', (_, name) => {
        const form = buildPresetForm(row({ name }), 'error_rate')

        expect(form.name.length).toBeLessThanOrEqual(255)
        expect(form.name).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/)
        expect(form.name.endsWith('…: error rate')).toBe(true)
    })

    it('starts the create form from the preset rather than the viewer filters', () => {
        initKeaTests()
        const initialForm = buildPresetForm(row(), 'p95_latency')
        const logic = tracesAlertFormLogic({
            alert: null,
            initialForm,
            viewerFilters: { serviceNames: ['other-service'], filterGroup: { type: 'AND', values: [] } as any },
        })
        logic.mount()

        expect(logic.values.alertForm).toEqual(initialForm)
    })
})

describe('presetDisabledReason', () => {
    it.each<[string, Partial<AggregatedSpanRow>, string | undefined]>([
        ['has entry spans', { entry_span_count: 12 }, undefined],
        // Internal or client spans only: the alert check would never see them.
        ['has no entry spans', { entry_span_count: 0 }, 'Alerts check entry spans (server, consumer or root) only'],
        ['comes from a result cached before the count existed', {}, undefined],
    ])('when the row %s', (_, overrides, reason) => {
        expect(presetDisabledReason(row(overrides))).toBe(reason)
    })
})
