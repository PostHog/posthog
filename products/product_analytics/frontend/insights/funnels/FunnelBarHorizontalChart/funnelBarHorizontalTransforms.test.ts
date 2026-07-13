import { EntityTypes, FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelBarHorizontalCompareData,
    buildFunnelBarHorizontalData,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
    resolveFunnelBarHorizontalHover,
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

    describe('compare funnel', () => {
        // Shared baseline: the larger period's first step (100) is the basis, so the previous bar
        // shows its real volume (0.8) rather than always filling the track.
        const compareSteps: FunnelStepWithConversionMetrics[] = [
            makeStep({
                count: 100,
                fromBasisStep: 1,
                name: 'Viewed',
                compare_label: 'current',
                nested_breakdown: [
                    makeStep({ count: 100, fromBasisStep: 1, name: 'Viewed', compare_label: 'current' }),
                    makeStep({ count: 80, fromBasisStep: 0.8, name: 'Viewed', compare_label: 'previous' }),
                ],
            }),
            makeStep({
                count: 50,
                fromBasisStep: 0.5,
                name: 'Signed up',
                compare_label: 'current',
                nested_breakdown: [
                    makeStep({ count: 50, fromBasisStep: 0.5, name: 'Signed up', compare_label: 'current' }),
                    makeStep({ count: 40, fromBasisStep: 0.4, name: 'Signed up', compare_label: 'previous' }),
                ],
            }),
        ]

        it('gives each step two bars (current then previous), each its own segment + filler', () => {
            const result = buildFunnelBarHorizontalCompareData(compareSteps, options)

            expect(result).toHaveLength(2)
            expect(result.every((step) => step.bars.length === 2)).toBe(true)
            expect(result.every((step) => step.bars.every((bar) => bar.series.length === 2))).toBe(true)
        })

        it('scales each bar to the shared baseline via fromBasisStep, each track summing segment + filler to 100', () => {
            const result = buildFunnelBarHorizontalCompareData(compareSteps, options)

            // current: 100% then 50%; previous: 80% then 40% — each on its own 0–100 track
            expect(result.map((s) => s.bars[0].series[0].data[0])).toEqual([100, 50])
            expect(result.map((s) => s.bars[0].series[1].data[0])).toEqual([0, 50])
            expect(result.map((s) => s.bars[1].series[0].data[0])).toEqual([80, 40])
            expect(result.map((s) => s.bars[1].series[1].data[0])).toEqual([20, 60])
        })

        it.each([
            {
                description: 'does not force the current step-0 bar to 100 when the previous period is larger',
                nested_breakdown: [
                    makeStep({ count: 80, fromBasisStep: 0.8, compare_label: 'current' }),
                    makeStep({ count: 100, fromBasisStep: 1, compare_label: 'previous' }),
                ],
                // current sits below the shared baseline; previous fills the track
                expectedBars: [
                    { segment: [80], filler: [20], breakdownIndex: 0 },
                    { segment: [100], filler: [0], breakdownIndex: 1 },
                ],
            },
            {
                description: 'renders a zeroed previous period as an empty track without error',
                nested_breakdown: [
                    makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current' }),
                    makeStep({ count: 0, fromBasisStep: 0, compare_label: 'previous' }),
                ],
                expectedBars: [
                    { segment: [100], filler: [0], breakdownIndex: 0 },
                    { segment: [0], filler: [100], breakdownIndex: 1 },
                ],
            },
            {
                description: 'renders a single bar when the step has no previous-period series',
                nested_breakdown: [makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current' })],
                expectedBars: [{ segment: [100], filler: [0], breakdownIndex: 0 }],
            },
        ])('$description', ({ nested_breakdown, expectedBars }) => {
            const steps: FunnelStepWithConversionMetrics[] = [
                makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current', nested_breakdown }),
            ]
            const [step] = buildFunnelBarHorizontalCompareData(steps, options)

            expect(step.bars).toHaveLength(expectedBars.length)
            expectedBars.forEach((expected, barIndex) => {
                expect(step.bars[barIndex].series[0].data).toEqual(expected.segment)
                expect(step.bars[barIndex].series[1].data).toEqual(expected.filler)
                expect(step.bars[barIndex].series[0].meta?.breakdownIndex).toBe(expected.breakdownIndex)
            })
        })

        it('colors each bar from the current step’s own variant, dimming the previous period', () => {
            const getColor = jest.fn((v: FunnelStepWithConversionMetrics) =>
                v.compare_label === 'previous' ? '#dimmed' : '#solid'
            )
            const result = buildFunnelBarHorizontalCompareData(compareSteps, { ...options, getColor })

            expect(result[1].bars[0].series[0].color).toBe('#solid')
            expect(result[1].bars[1].series[0].color).toBe('#dimmed')
            // representative is step 1's own variant (per-step color), not step 0's
            expect(getColor).toHaveBeenCalledWith(compareSteps[1].nested_breakdown![0])
            expect(getColor).toHaveBeenCalledWith(compareSteps[1].nested_breakdown![1])
        })

        it('tags both the segment and filler of each bar with its period breakdownIndex', () => {
            const [step] = buildFunnelBarHorizontalCompareData(compareSteps, options)

            expect(step.bars[0].series[0].meta).toEqual({ isDropOff: false, breakdownIndex: 0 })
            expect(step.bars[0].series[1].meta).toEqual({ isDropOff: true, breakdownIndex: 0 })
            expect(step.bars[1].series[0].meta).toEqual({ isDropOff: false, breakdownIndex: 1 })
            expect(step.bars[1].series[1].meta).toEqual({ isDropOff: true, breakdownIndex: 1 })
        })

        describe('with breakdown', () => {
            // Breakdown + compare: nested_breakdown is paired [value0 current, value0 previous, …], so each
            // (value, period) gets its own full-track bar — no overflow from stacking variants scaled to the
            // grouped-bar baseline — and bars read paired by breakdown value with the previous one dimmed.
            const breakdownCompareSteps: FunnelStepWithConversionMetrics[] = [
                makeStep({
                    count: 140,
                    fromBasisStep: 1,
                    compare_label: 'current',
                    nested_breakdown: [
                        makeStep({ count: 100, fromBasisStep: 1, breakdown_value: 'mobile', compare_label: 'current' }),
                        makeStep({
                            count: 80,
                            fromBasisStep: 0.8,
                            breakdown_value: 'mobile',
                            compare_label: 'previous',
                        }),
                        makeStep({
                            count: 40,
                            fromBasisStep: 0.4,
                            breakdown_value: 'desktop',
                            compare_label: 'current',
                        }),
                        makeStep({
                            count: 25,
                            fromBasisStep: 0.25,
                            breakdown_value: 'desktop',
                            compare_label: 'previous',
                        }),
                    ],
                }),
            ]

            it('renders one full-track bar per (breakdown value, period)', () => {
                const [step] = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, options)

                expect(step.bars).toHaveLength(4)
                expect(step.bars.map((bar) => bar.series[0].data[0])).toEqual([100, 80, 40, 25])
                expect(step.bars.map((bar) => bar.series[0].meta?.breakdownIndex)).toEqual([0, 1, 2, 3])
            })

            it('dims each breakdown value’s previous-period bar', () => {
                const getColor = jest.fn((v: FunnelStepWithConversionMetrics) =>
                    v.compare_label === 'previous' ? '#dimmed' : '#solid'
                )
                const [step] = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, { ...options, getColor })

                expect(step.bars.map((bar) => bar.series[0].color)).toEqual(['#solid', '#dimmed', '#solid', '#dimmed'])
            })
        })
    })

    describe('resolveFunnelBarHorizontalHover', () => {
        // Aggregate steps inherit breakdown_value from their first variant (aggregateBreakdownResult
        // spreads it) — mirrored here so the whole-step case proves the label gets cleared.
        const step = makeStep({
            count: 40,
            fromBasisStep: 0.4,
            name: 'Signed up',
            breakdown_value: 'mobile',
            nested_breakdown: [
                makeStep({ count: 30, fromBasisStep: 0.5, breakdown_value: 'mobile' }),
                makeStep({ count: 10, fromBasisStep: 0.25, breakdown_value: 'desktop' }),
            ],
        })

        const segmentEntry = (
            breakdownIndex: number | null,
            color: string
        ): {
            series: { key: string; label: string; data: number[]; meta: FunnelBarHorizontalSegmentMeta }
            value: number
            color: string
            yPixel: number
        } => ({
            series: {
                key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex ?? 0}`,
                label: '',
                data: [0],
                meta: { isDropOff: false, breakdownIndex },
            },
            value: 0,
            color,
            yPixel: 100,
        })
        const breakdownSeriesData = [segmentEntry(0, '#aaa'), segmentEntry(1, '#bbb')]

        it.each([
            {
                description: 'hovering a later breakdown segment resolves that variant, not the first',
                seriesData: breakdownSeriesData,
                hoveredSeriesKey: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}1`,
                hoverPosition: null,
                expected: { series: step.nested_breakdown![1], isDropOffHover: false, color: '#bbb' },
            },
            {
                description:
                    'hovering the filler on a breakdown bar resolves the whole step as drop-off, without the inherited breakdown label',
                seriesData: breakdownSeriesData,
                hoveredSeriesKey: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
                hoverPosition: null,
                expected: {
                    series: { ...step, breakdown: undefined, breakdown_value: undefined },
                    isDropOffHover: true,
                    color: undefined,
                },
            },
            {
                description: 'hovering the filler on a single-segment bar (compare) resolves its variant as drop-off',
                seriesData: [segmentEntry(1, '#ccc')],
                hoveredSeriesKey: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
                hoverPosition: null,
                expected: { series: step.nested_breakdown![1], isDropOffHover: true, color: '#ccc' },
            },
            {
                description: 'without a hovered key, falls back to the first segment + cursor-past-end heuristic',
                seriesData: breakdownSeriesData,
                hoveredSeriesKey: undefined,
                hoverPosition: { x: 150, y: 10 },
                expected: { series: step.nested_breakdown![0], isDropOffHover: true, color: '#aaa' },
            },
        ])('$description', ({ seriesData, hoveredSeriesKey, hoverPosition, expected }) => {
            const target = resolveFunnelBarHorizontalHover({ hoveredSeriesKey, seriesData, hoverPosition }, step, 1)
            expect(target?.series).toEqual(expected.series)
            expect(target?.isDropOffHover).toBe(expected.isDropOffHover)
            expect(target?.color).toBe(expected.color)
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
