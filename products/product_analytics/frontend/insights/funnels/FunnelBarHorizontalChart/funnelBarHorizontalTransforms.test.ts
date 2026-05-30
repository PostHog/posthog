import { EntityTypes, FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

import { buildFunnelBarHorizontalData, FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX } from './funnelBarHorizontalTransforms'

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
}

describe('buildFunnelBarHorizontalData', () => {
    it('returns empty series + labels when given no steps', () => {
        expect(buildFunnelBarHorizontalData([], options)).toEqual({ series: [], labels: [] })
    })

    it('emits one label per step', () => {
        const steps = [
            makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
            makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
            makeStep({ count: 20, fromBasisStep: 0.2, name: 'Purchased' }),
        ]
        const { labels } = buildFunnelBarHorizontalData(steps, options)
        expect(labels).toHaveLength(3)
    })

    describe('non-breakdown funnel', () => {
        const noBreakdownSteps = [
            makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed' }),
            makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up' }),
            makeStep({ count: 20, fromBasisStep: 0.2, name: 'Purchased' }),
        ]

        it('emits a single value series with one percentage per step (remainder is the chart track)', () => {
            const { series } = buildFunnelBarHorizontalData(noBreakdownSteps, options)

            expect(series).toHaveLength(1)
            expect(series[0].data).toEqual([100, 50, 20])
        })

        it('tags the segment with a null breakdownIndex for click + tooltip routing', () => {
            const { series } = buildFunnelBarHorizontalData(noBreakdownSteps, options)

            expect(series[0].meta).toEqual({ breakdownIndex: null })
        })

        it('colors the segment from the representative step', () => {
            const getColor = jest.fn(() => '#abcabc')
            const { series } = buildFunnelBarHorizontalData(noBreakdownSteps, { ...options, getColor })

            expect(series[0].color).toBe('#abcabc')
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

        it('emits one series per variant', () => {
            const { series } = buildFunnelBarHorizontalData(breakdownSteps, options)

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.label)).toEqual(['mobile', 'desktop'])
        })

        it('builds per-step fractions per variant against the configured basis step', () => {
            const { series } = buildFunnelBarHorizontalData(breakdownSteps, options)
            expect(series[0].data).toEqual([60, 30])
            expect(series[1].data).toEqual([40, 10])
        })

        it('tags each segment with its source breakdownIndex', () => {
            const { series } = buildFunnelBarHorizontalData(breakdownSteps, options)
            expect(series[0].meta).toEqual({ breakdownIndex: 0 })
            expect(series[1].meta).toEqual({ breakdownIndex: 1 })
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

            const { series } = buildFunnelBarHorizontalData(skewed, options)
            expect(series).toHaveLength(2)
            expect(series[0].data).toEqual([60, 50]) // mobile
            expect(series[1].data).toEqual([40, 0]) // desktop — missing in step 1
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

        it('collapses to one segment sourced from the single visible variant', () => {
            const { series } = buildFunnelBarHorizontalData(collapsedSteps, { ...options, breakdownFilter })

            expect(series).toHaveLength(1)
            expect(series[0].label).toBe('mobile')
            expect(series[0].data).toEqual([100, 50])
            expect(series[0].meta?.breakdownIndex).toBe(0)
        })

        it('falls back to the parent step’s rate when no breakdownFilter is set', () => {
            const { series } = buildFunnelBarHorizontalData(collapsedSteps, options)

            expect(series[0].data).toEqual([100, 50])
            expect(series[0].meta?.breakdownIndex).toBeNull()
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
                const { series } = buildFunnelBarHorizontalData(steps, { ...options, stepReference })
                expect(series[0].data).toEqual(expected)
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
            const { series } = buildFunnelBarHorizontalData(steps, {
                ...options,
                stepReference: FunnelStepReference.previous,
            })
            // Step 0 has no nested_breakdown, so non-breakdown path is taken regardless of stepReference.
            expect(series[0].data).toEqual([100, 50, 30])
        })
    })

    describe('zero-basis-count step', () => {
        it('emits zero-width segments when basisStep.count is 0 (the track fills the row)', () => {
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
            const { series } = buildFunnelBarHorizontalData(steps, options)
            expect(series.map((s) => s.data)).toEqual([
                [0, 0],
                [0, 0],
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
            const { series } = buildFunnelBarHorizontalData(steps, options)
            expect(series.map((s) => s.key)).toEqual([
                `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
                `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}1`,
            ])
        })
    })
})
