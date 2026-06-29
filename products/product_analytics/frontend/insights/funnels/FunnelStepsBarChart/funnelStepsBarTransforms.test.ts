import type { PointClickData, Series } from '@posthog/quill-charts'

import { EntityTypes, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelStepsBarData,
    FUNNEL_STEPS_SERIES_KEY_PREFIX,
    type FunnelStepsBarSeriesMeta,
    resolveFunnelStepClick,
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

// Pure compare: the previous period (0.8 entry) is shorter than the current (1.0) on the shared baseline.
const compareSteps: FunnelStepWithConversionMetrics[] = [
    makeStep({
        fromBasisStep: 1,
        compare_label: 'current',
        nested_breakdown: [
            makeStep({ fromBasisStep: 1, compare_label: 'current' }),
            makeStep({ fromBasisStep: 0.8, compare_label: 'previous' }),
        ],
    }),
    makeStep({
        fromBasisStep: 0.5,
        compare_label: 'current',
        nested_breakdown: [
            makeStep({ fromBasisStep: 0.5, compare_label: 'current' }),
            makeStep({ fromBasisStep: 0.4, compare_label: 'previous' }),
        ],
    }),
]

const breakdownCompareSteps: FunnelStepWithConversionMetrics[] = [
    makeStep({
        fromBasisStep: 1,
        compare_label: 'current',
        nested_breakdown: [
            makeStep({ fromBasisStep: 1, breakdown_value: 'mobile', compare_label: 'current' }),
            makeStep({ fromBasisStep: 0.8, breakdown_value: 'mobile', compare_label: 'previous' }),
            makeStep({ fromBasisStep: 0.4, breakdown_value: 'desktop', compare_label: 'current' }),
            makeStep({ fromBasisStep: 0.25, breakdown_value: 'desktop', compare_label: 'previous' }),
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

    it('renders previous before current and caps the shorter period’s track', () => {
        const { series } = buildFunnelStepsBarData(compareSteps, options)

        // Left-to-right layout flips the nested_breakdown order: previous (breakdownIndex 1) renders
        // first, current (0) second. The shorter previous period is capped at its 80% entry level;
        // current sits at the baseline (no cap).
        expect(series.map((s) => s.meta?.breakdownIndex)).toEqual([1, 0])
        expect(series.map((s) => s.trackMax)).toEqual([80, undefined])
    })

    it('swaps current/previous within each breakdown value for breakdown × compare', () => {
        const { series } = buildFunnelStepsBarData(breakdownCompareSteps, options)

        // Each value's [current, previous] pair flips to [previous, current]: v0p, v0c, v1p, v1c.
        expect(series.map((s) => s.meta?.breakdownIndex)).toEqual([1, 0, 3, 2])
    })

    it.each([
        { name: 'a non-compare funnel', steps: noBreakdownSteps },
        // breakdown × compare headroom mixes "smaller breakdown" with "smaller period", so no cap
        { name: 'breakdown × compare', steps: breakdownCompareSteps },
    ])('sets no trackMax for $name', ({ steps }) => {
        const { series } = buildFunnelStepsBarData(steps, options)

        expect(series.every((s) => s.trackMax === undefined)).toBe(true)
    })

    it('keeps non-compare breakdown series in their original order', () => {
        const { series } = buildFunnelStepsBarData(breakdownSteps, options)

        expect(series.map((s) => s.meta?.breakdownIndex)).toEqual([0, 1])
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

type ClickFields = Pick<
    PointClickData<FunnelStepsBarSeriesMeta>,
    'dataIndex' | 'series' | 'inTrackArea' | 'beyondTrackMax'
>

function makeClick(overrides: Partial<ClickFields>): ClickFields {
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

    it('returns null in the inert "not present" headroom (beyondTrackMax), opening no actors', () => {
        const target = resolveFunnelStepClick(
            noBreakdownSteps,
            makeClick({ dataIndex: 1, inTrackArea: true, beyondTrackMax: true })
        )

        expect(target).toBeNull()
    })
})
