import type { BarChartConfig, PointClickData, Series } from '@posthog/quill-charts'

import { EntityTypes, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelStepsBarData,
    FUNNEL_STEPS_SERIES_KEY_PREFIX,
    resolveFunnelStepClick,
    withFunnelStepsBarInteraction,
    type FunnelStepsBarSeriesMeta,
} from './funnelStepsBarTransforms'

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

function makeSeries(breakdownIndex: number): Series<FunnelStepsBarSeriesMeta> {
    return {
        key: `${FUNNEL_STEPS_SERIES_KEY_PREFIX}${breakdownIndex}`,
        label: 'series',
        data: [],
        meta: { breakdownIndex },
    }
}

function makeClick(
    overrides: Partial<Pick<PointClickData<FunnelStepsBarSeriesMeta>, 'dataIndex' | 'series' | 'inTrackArea'>>
): Pick<PointClickData<FunnelStepsBarSeriesMeta>, 'dataIndex' | 'series' | 'inTrackArea'> {
    return { dataIndex: 0, series: makeSeries(0), ...overrides }
}

describe('resolveFunnelStepClick', () => {
    it.each<[string, boolean | undefined, boolean]>([
        ['filled bar (inTrackArea false) opens converted', false, true],
        ['track above the bar (inTrackArea true) opens drop-off', true, false],
        ['non-grouped click (inTrackArea undefined) falls back to converted', undefined, true],
    ])('%s', (_name, inTrackArea, expectedConverted) => {
        const target = resolveFunnelStepClick(noBreakdownSteps, makeClick({ dataIndex: 1, inTrackArea }))

        expect(target).not.toBeNull()
        expect(target?.step).toBe(noBreakdownSteps[1])
        expect(target?.series).toBe(noBreakdownSteps[1])
        expect(target?.converted).toBe(expectedConverted)
    })

    it('resolves the breakdown variant via the series meta breakdownIndex', () => {
        const target = resolveFunnelStepClick(
            breakdownSteps,
            makeClick({ dataIndex: 1, series: makeSeries(1), inTrackArea: false })
        )

        expect(target?.step).toBe(breakdownSteps[1])
        expect(target?.series).toBe(breakdownSteps[1].nested_breakdown?.[1])
        expect(target?.converted).toBe(true)
    })

    it('returns null when the clicked column has no step', () => {
        expect(resolveFunnelStepClick(noBreakdownSteps, makeClick({ dataIndex: 99 }))).toBeNull()
    })
})

describe('withFunnelStepsBarInteraction', () => {
    const baseConfig: BarChartConfig = { barLayout: 'grouped', tooltip: { placement: 'top' } }

    it('returns the base config unchanged when the new tooltip is off', () => {
        const config = withFunnelStepsBarInteraction(baseConfig, { quillTooltipEnabled: false })

        expect(config).toBe(baseConfig)
    })

    it('enables a pinnable tooltip that resolves clicks to the nearest series when the new tooltip is on', () => {
        // A breakdown puts one series per breakdown value at each step, so a pinnable tooltip
        // here always covers multiple series — resolveClickToNearestSeries must stay set or a
        // click pins the tooltip instead of opening the persons modal (the bug this guards).
        const config = withFunnelStepsBarInteraction(baseConfig, { quillTooltipEnabled: true })

        expect(config.tooltip).toEqual({ pinnable: true, resolveClickToNearestSeries: true, placement: 'cursor' })
    })

    it('adds a static legend for breakdown + compare, independent of the tooltip flag', () => {
        const config = withFunnelStepsBarInteraction(baseConfig, {
            isBreakdownCompare: true,
            quillTooltipEnabled: false,
        })

        expect(config.legend).toEqual({ show: true, interactive: false })
    })
})
