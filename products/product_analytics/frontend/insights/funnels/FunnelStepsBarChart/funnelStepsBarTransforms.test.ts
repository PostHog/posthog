import { EntityTypes, type FunnelStepWithConversionMetrics } from '~/types'

import { buildFunnelStepsBarData, FUNNEL_STEPS_SERIES_KEY_PREFIX } from './funnelStepsBarTransforms'

type StepOverrides = Partial<FunnelStepWithConversionMetrics> & { fromBasisStep: number }

function makeStep({ fromBasisStep, ...overrides }: StepOverrides): FunnelStepWithConversionMetrics {
    return {
        action_id: 'action',
        average_conversion_time: null,
        median_conversion_time: null,
        count: 0,
        name: 'Step',
        order: 0,
        type: EntityTypes.EVENTS,
        converted_people_url: '',
        dropped_people_url: null,
        droppedOffFromPrevious: 0,
        conversionRates: { fromPrevious: fromBasisStep, total: fromBasisStep, fromBasisStep },
        ...overrides,
    }
}

const noBreakdownSteps: FunnelStepWithConversionMetrics[] = [
    makeStep({ fromBasisStep: 1, name: 'Viewed' }),
    makeStep({ fromBasisStep: 0.5, name: 'Signed up' }),
    makeStep({ fromBasisStep: 0.2, name: 'Purchased' }),
]

const breakdownSteps: FunnelStepWithConversionMetrics[] = [
    makeStep({
        fromBasisStep: 1,
        nested_breakdown: [
            makeStep({ fromBasisStep: 1, breakdown_value: 'mobile' }),
            makeStep({ fromBasisStep: 1, breakdown_value: 'desktop' }),
        ],
    }),
    makeStep({
        fromBasisStep: 0.4,
        nested_breakdown: [
            makeStep({ fromBasisStep: 0.6, breakdown_value: 'mobile' }),
            makeStep({ fromBasisStep: 0.3, breakdown_value: 'desktop' }),
        ],
    }),
]

const options = {
    getColor: () => '#1d4aff',
    getLabel: (variant: FunnelStepWithConversionMetrics) => String(variant.breakdown_value ?? variant.name),
}

describe('buildFunnelStepsBarData', () => {
    it('builds a single series valued by conversion rate when there is no breakdown', () => {
        const { series, labels } = buildFunnelStepsBarData(noBreakdownSteps, options)

        expect(series).toHaveLength(1)
        expect(series[0].key).toBe(`${FUNNEL_STEPS_SERIES_KEY_PREFIX}0`)
        expect(series[0].data).toEqual([100, 50, 20])
        expect(labels).toEqual(['1', '2', '3'])
    })

    it('builds one series per breakdown variant', () => {
        const { series } = buildFunnelStepsBarData(breakdownSteps, options)

        expect(series).toHaveLength(2)
        expect(series[0].data).toEqual([100, 60])
        expect(series[1].data).toEqual([100, 30])
    })

    it('tags each series with its breakdown index for click/tooltip mapping', () => {
        const { series } = buildFunnelStepsBarData(breakdownSteps, options)

        expect(series.map((s) => s.meta?.breakdownIndex)).toEqual([0, 1])
    })

    it('labels and colors each series from its representative variant', () => {
        const getColor = jest.fn(() => '#1d4aff')
        const { series } = buildFunnelStepsBarData(breakdownSteps, { ...options, getColor })

        expect(series.map((s) => s.label)).toEqual(['mobile', 'desktop'])
        expect(getColor).toHaveBeenCalledWith(breakdownSteps[0].nested_breakdown?.[0])
    })

    it('zeroes the bar when a step is missing a breakdown variant (not inflating to the parent rate)', () => {
        const skewedSteps: FunnelStepWithConversionMetrics[] = [
            makeStep({
                fromBasisStep: 1,
                nested_breakdown: [
                    makeStep({ fromBasisStep: 1, breakdown_value: 'mobile' }),
                    makeStep({ fromBasisStep: 1, breakdown_value: 'desktop' }),
                ],
            }),
            makeStep({
                fromBasisStep: 0.5,
                // Only one variant in step 2 — the missing 'desktop' variant must not inherit
                // the parent's 50% aggregate, or the chart misrepresents reality.
                nested_breakdown: [makeStep({ fromBasisStep: 0.7, breakdown_value: 'mobile' })],
            }),
        ]

        const { series } = buildFunnelStepsBarData(skewedSteps, options)

        expect(series).toHaveLength(2)
        expect(series[0].data).toEqual([100, 70])
        expect(series[1].data).toEqual([100, 0])
    })

    it('handles an empty step list', () => {
        const { series, labels } = buildFunnelStepsBarData([], options)

        expect(series).toEqual([])
        expect(labels).toEqual([])
    })
})
