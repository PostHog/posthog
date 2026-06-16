import { EntityTypes, FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelBarHorizontalData,
    type FunnelBarHorizontalStepData,
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
} from './funnelBarHorizontalTransforms'

type StepOverrides = Partial<FunnelStepWithConversionMetrics> & {
    fromBasisStep: number
    fromPrevious?: number
    total?: number
}

function makeStep({
    fromBasisStep,
    fromPrevious,
    total,
    ...overrides
}: StepOverrides): FunnelStepWithConversionMetrics {
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
        conversionRates: {
            fromPrevious: fromPrevious ?? fromBasisStep,
            total: total ?? fromBasisStep,
            fromBasisStep,
        },
        ...overrides,
    }
}

const options = {
    stepReference: FunnelStepReference.total,
    getColor: () => '#1d4aff',
    getLabel: (variant: FunnelStepWithConversionMetrics) => String(variant.breakdown_value ?? variant.name),
    fillerColor: '#eef0f3',
}

/** Collects one series' value across every step, for asserting against the old per-step arrays. */
function dataAcross(steps: FunnelBarHorizontalStepData[], seriesIndex: number): number[] {
    return steps.map((s) => s.series[seriesIndex].data[0])
}

describe('buildFunnelBarHorizontalData', () => {
    it('returns no steps when given no steps', () => {
        expect(buildFunnelBarHorizontalData([], options)).toEqual([])
    })

    it('emits one entry per step, each labeled by its index', () => {
        const steps = [
            makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
            makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
            makeStep({ count: 20, fromBasisStep: 0.2, name: 'Purchased' }),
        ]
        const result = buildFunnelBarHorizontalData(steps, options)
        expect(result).toHaveLength(3)
        expect(result.map((s) => s.label)).toEqual(['0', '1', '2'])
    })

    describe('non-breakdown funnel', () => {
        const noBreakdownSteps = [
            makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
            makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
            makeStep({ count: 20, fromBasisStep: 0.2, name: 'Purchased' }),
        ]

        it('gives each step one segment series + one filler series, each holding a single value', () => {
            const result = buildFunnelBarHorizontalData(noBreakdownSteps, options)

            expect(result.every((s) => s.series.length === 2)).toBe(true)
            expect(result.every((s) => s.series.every((entry) => entry.data.length === 1))).toBe(true)
            expect(dataAcross(result, 0)).toEqual([100, 50, 20])
            expect(dataAcross(result, 1)).toEqual([0, 50, 80])
        })

        it('tags each series with its drop-off / breakdown role for click + tooltip routing', () => {
            const [first] = buildFunnelBarHorizontalData(noBreakdownSteps, options)

            expect(first.series[0].meta).toEqual({ isDropOff: false, breakdownIndex: null })
            expect(first.series[1].meta).toEqual({ isDropOff: true, breakdownIndex: null })
        })

        it('hides the filler from the tooltip so it doesn’t double up with FunnelTooltip’s drop-off section', () => {
            const [first] = buildFunnelBarHorizontalData(noBreakdownSteps, options)
            expect(first.series[1].visibility?.tooltip).toBe(false)
        })

        it('colors the segment from the step and the filler from options.fillerColor', () => {
            const getColor = jest.fn(() => '#abcabc')
            const [first] = buildFunnelBarHorizontalData(noBreakdownSteps, { ...options, getColor })

            expect(first.series[0].color).toBe('#abcabc')
            expect(first.series[1].color).toBe(options.fillerColor)
            expect(getColor).toHaveBeenCalledWith(noBreakdownSteps[0])
        })
    })

    describe('breakdown funnel', () => {
        const breakdownSteps = [
            makeStep({
                count: 100,
                fromBasisStep: 1,
                nested_breakdown: [
                    makeStep({ count: 60, fromBasisStep: 1, breakdown_value: 'mobile' }),
                    makeStep({ count: 40, fromBasisStep: 1, breakdown_value: 'desktop' }),
                ],
            }),
            makeStep({
                count: 40,
                fromBasisStep: 0.4,
                nested_breakdown: [
                    makeStep({ count: 30, fromBasisStep: 0.5, breakdown_value: 'mobile' }),
                    makeStep({ count: 10, fromBasisStep: 0.25, breakdown_value: 'desktop' }),
                ],
            }),
        ]

        it('gives each step one series per variant plus the trailing filler', () => {
            const result = buildFunnelBarHorizontalData(breakdownSteps, options)

            expect(result.every((s) => s.series.length === 3)).toBe(true)
            expect(result[0].series.map((s) => s.label)).toEqual(['mobile', 'desktop', 'Drop-off'])
        })

        it('builds per-step fractions per variant against the configured basis step', () => {
            const result = buildFunnelBarHorizontalData(breakdownSteps, options)
            expect(dataAcross(result, 0)).toEqual([60, 30])
            expect(dataAcross(result, 1)).toEqual([40, 10])
            expect(dataAcross(result, 2)).toEqual([0, 60])
        })

        it('tags each segment with its source breakdownIndex', () => {
            const [first] = buildFunnelBarHorizontalData(breakdownSteps, options)
            expect(first.series[0].meta).toEqual({ isDropOff: false, breakdownIndex: 0 })
            expect(first.series[1].meta).toEqual({ isDropOff: false, breakdownIndex: 1 })
        })

        it('zeros a missing variant at a later step rather than rolling its count into another bar', () => {
            const skewed = [
                makeStep({
                    count: 100,
                    fromBasisStep: 1,
                    nested_breakdown: [
                        makeStep({ count: 60, fromBasisStep: 1, breakdown_value: 'mobile' }),
                        makeStep({ count: 40, fromBasisStep: 1, breakdown_value: 'desktop' }),
                    ],
                }),
                makeStep({
                    count: 50,
                    fromBasisStep: 0.5,
                    nested_breakdown: [makeStep({ count: 50, fromBasisStep: 0.5, breakdown_value: 'mobile' })],
                }),
            ]

            const result = buildFunnelBarHorizontalData(skewed, options)
            expect(result.every((s) => s.series.length === 3)).toBe(true)
            expect(dataAcross(result, 0)).toEqual([60, 50]) // mobile
            expect(dataAcross(result, 1)).toEqual([40, 0]) // desktop — missing in step 1
            expect(dataAcross(result, 2)).toEqual([0, 50]) // filler
        })
    })

    describe('single-visible-breakdown collapse', () => {
        const collapsedSteps = [
            makeStep({
                count: 100,
                fromBasisStep: 1,
                nested_breakdown: [makeStep({ count: 100, fromBasisStep: 1, breakdown_value: 'mobile' })],
            }),
            makeStep({
                count: 50,
                fromBasisStep: 0.5,
                nested_breakdown: [makeStep({ count: 50, fromBasisStep: 0.5, breakdown_value: 'mobile' })],
            }),
        ]
        const breakdownFilter = { breakdown: '$browser' }

        it('collapses to one segment + filler, sourced from the single visible variant', () => {
            const result = buildFunnelBarHorizontalData(collapsedSteps, { ...options, breakdownFilter })

            expect(result.every((s) => s.series.length === 2)).toBe(true)
            expect(result[0].series[0].label).toBe('mobile')
            expect(dataAcross(result, 0)).toEqual([100, 50])
            expect(result[0].series[0].meta?.breakdownIndex).toBe(0)
            expect(dataAcross(result, 1)).toEqual([0, 50])
        })

        it('falls back to the parent step’s rate when no breakdownFilter is set', () => {
            const result = buildFunnelBarHorizontalData(collapsedSteps, options)

            expect(dataAcross(result, 0)).toEqual([100, 50])
            expect(result[0].series[0].meta?.breakdownIndex).toBeNull()
        })
    })

    describe('reference step', () => {
        it.each([
            { stepReference: FunnelStepReference.total, expected: [100, 50, 20] },
            { stepReference: FunnelStepReference.previous, expected: [100, 50, 20] },
        ])(
            'uses precomputed fromBasisStep for non-breakdown layouts (stepReference=$stepReference)',
            ({ stepReference, expected }) => {
                const steps = [
                    makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
                    makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
                    makeStep({ count: 20, fromBasisStep: 0.2, name: 'Purchased' }),
                ]
                const result = buildFunnelBarHorizontalData(steps, { ...options, stepReference })
                expect(dataAcross(result, 0)).toEqual(expected)
            }
        )

        it('honors stepReference.previous as the basis for breakdown fractions', () => {
            const steps: FunnelStepWithConversionMetrics[] = [
                makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
                makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
                makeStep({
                    count: 30,
                    fromBasisStep: 0.3,
                    name: 'Purchased',
                    nested_breakdown: [
                        makeStep({ count: 20, fromBasisStep: 0.4, breakdown_value: 'mobile' }),
                        makeStep({ count: 10, fromBasisStep: 0.2, breakdown_value: 'desktop' }),
                    ],
                }),
            ]
            const result = buildFunnelBarHorizontalData(steps, {
                ...options,
                stepReference: FunnelStepReference.previous,
            })
            // Step 0 has no nested_breakdown, so the non-breakdown path is taken regardless of stepReference.
            expect(dataAcross(result, 0)).toEqual([100, 50, 30])
        })
    })

    describe('zero-basis-count step', () => {
        it('emits a zero segment + full filler when basisStep.count is 0', () => {
            const steps = [
                makeStep({
                    count: 0,
                    fromBasisStep: 0,
                    name: 'Viewed',
                    nested_breakdown: [
                        makeStep({ count: 0, fromBasisStep: 0, breakdown_value: 'mobile' }),
                        makeStep({ count: 0, fromBasisStep: 0, breakdown_value: 'desktop' }),
                    ],
                }),
                makeStep({
                    count: 0,
                    fromBasisStep: 0,
                    name: 'Purchased',
                    nested_breakdown: [
                        makeStep({ count: 0, fromBasisStep: 0, breakdown_value: 'mobile' }),
                        makeStep({ count: 0, fromBasisStep: 0, breakdown_value: 'desktop' }),
                    ],
                }),
            ]
            const result = buildFunnelBarHorizontalData(steps, options)
            expect([dataAcross(result, 0), dataAcross(result, 1), dataAcross(result, 2)]).toEqual([
                [0, 0],
                [0, 0],
                [100, 100],
            ])
        })
    })

    describe('series keys', () => {
        it('namespaces segment keys by breakdown index', () => {
            const steps = [
                makeStep({
                    count: 100,
                    fromBasisStep: 1,
                    nested_breakdown: [
                        makeStep({ count: 60, fromBasisStep: 1, breakdown_value: 'mobile' }),
                        makeStep({ count: 40, fromBasisStep: 1, breakdown_value: 'desktop' }),
                    ],
                }),
                makeStep({
                    count: 50,
                    fromBasisStep: 0.5,
                    nested_breakdown: [
                        makeStep({ count: 30, fromBasisStep: 0.5, breakdown_value: 'mobile' }),
                        makeStep({ count: 20, fromBasisStep: 0.4, breakdown_value: 'desktop' }),
                    ],
                }),
            ]
            const [first] = buildFunnelBarHorizontalData(steps, options)
            expect(first.series.map((s) => s.key)).toEqual([
                `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
                `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}1`,
                FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
            ])
        })
    })
})
