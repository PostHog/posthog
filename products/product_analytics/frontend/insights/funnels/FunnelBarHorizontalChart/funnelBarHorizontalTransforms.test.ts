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

/** Sum of a stacked bar's segment values (how far it fills the shared 0–100 axis). */
function stackTotal(bar: FunnelBarHorizontalStepData): number {
    return bar.series.reduce((sum, s) => sum + s.data[0], 0)
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

        it('stops each period’s drop-off at its own entry level, leaving the volume gap blank', () => {
            const result = buildFunnelBarHorizontalCompareData(compareSteps, options)

            // Current is the leader (entry 100%): segment + drop-off fill the track to 100.
            expect(result.map((s) => s.bars[0].series[0].data[0])).toEqual([100, 50])
            expect(result.map((s) => s.bars[0].series[1].data[0])).toEqual([0, 50])
            // Previous entry level is 80%, so its bars sum to 80, never 100 — the 20 above is the blank
            // volume gap (fewer entrants), not drop-off, so it's left as whitespace (no segment).
            expect(result.map((s) => s.bars[1].series[0].data[0])).toEqual([80, 40])
            expect(result.map((s) => s.bars[1].series[1].data[0])).toEqual([0, 40])
            expect(result.map((s) => s.bars[1].series[0].data[0] + s.bars[1].series[1].data[0])).toEqual([80, 80])
            // Each drop-off declares its period's entry level as the bar's interactive ceiling, so the
            // chart treats the blank gap above it as inert (no hover, tooltip, pointer cursor, or click).
            expect(result.map((s) => s.bars[0].series[1].trackData)).toEqual([[100], [100]])
            expect(result.map((s) => s.bars[1].series[1].trackData)).toEqual([[80], [80]])
        })

        // At the first step every bar sits exactly at its own entry level, so drop-off is always 0 —
        // the shorter period's remainder to 100 is the blank volume gap (whitespace), not drop-off.
        it.each([
            {
                description: 'does not force the current step-0 bar to 100 when the previous period is larger',
                nested_breakdown: [
                    makeStep({ count: 80, fromBasisStep: 0.8, compare_label: 'current' }),
                    makeStep({ count: 100, fromBasisStep: 1, compare_label: 'previous' }),
                ],
                // current sits below the shared baseline — its 20 to the top is blank, not drop-off
                expectedBars: [
                    { segment: [80], dropOff: [0], breakdownIndex: 0 },
                    { segment: [100], dropOff: [0], breakdownIndex: 1 },
                ],
            },
            {
                description: 'renders a zeroed previous period as an all-blank bar (no phantom drop-off)',
                nested_breakdown: [
                    makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current' }),
                    makeStep({ count: 0, fromBasisStep: 0, compare_label: 'previous' }),
                ],
                expectedBars: [
                    { segment: [100], dropOff: [0], breakdownIndex: 0 },
                    { segment: [0], dropOff: [0], breakdownIndex: 1 },
                ],
            },
            {
                description: 'renders a single bar when the step has no previous-period series',
                nested_breakdown: [makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current' })],
                expectedBars: [{ segment: [100], dropOff: [0], breakdownIndex: 0 }],
            },
        ])('$description', ({ nested_breakdown, expectedBars }) => {
            const steps: FunnelStepWithConversionMetrics[] = [
                makeStep({ count: 100, fromBasisStep: 1, compare_label: 'current', nested_breakdown }),
            ]
            const [step] = buildFunnelBarHorizontalCompareData(steps, options)

            expect(step.bars).toHaveLength(expectedBars.length)
            expectedBars.forEach((expected, barIndex) => {
                expect(step.bars[barIndex].series[0].data).toEqual(expected.segment)
                expect(step.bars[barIndex].series[1].data).toEqual(expected.dropOff)
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
            // Breakdown + compare: two stacks per step (current, then previous), each split into the same
            // breakdown-value segments and scaled to whichever period had more total entrants. nested_breakdown
            // is paired [value0 current, value0 previous, …]; fromBasisStep is unused here (the stacks scale by
            // raw count / max-period-total, not per-value).
            const breakdownCompareSteps: FunnelStepWithConversionMetrics[] = [
                makeStep({
                    count: 100,
                    fromBasisStep: 1,
                    compare_label: 'current',
                    nested_breakdown: [
                        makeStep({ count: 60, fromBasisStep: 1, breakdown_value: 'mobile', compare_label: 'current' }),
                        makeStep({ count: 45, fromBasisStep: 1, breakdown_value: 'mobile', compare_label: 'previous' }),
                        makeStep({ count: 40, fromBasisStep: 1, breakdown_value: 'desktop', compare_label: 'current' }),
                        makeStep({
                            count: 30,
                            fromBasisStep: 1,
                            breakdown_value: 'desktop',
                            compare_label: 'previous',
                        }),
                    ],
                }),
                makeStep({
                    count: 50,
                    fromBasisStep: 0.5,
                    compare_label: 'current',
                    nested_breakdown: [
                        makeStep({
                            count: 30,
                            fromBasisStep: 0.5,
                            breakdown_value: 'mobile',
                            compare_label: 'current',
                        }),
                        makeStep({
                            count: 15,
                            fromBasisStep: 0.5,
                            breakdown_value: 'mobile',
                            compare_label: 'previous',
                        }),
                        makeStep({
                            count: 20,
                            fromBasisStep: 0.5,
                            breakdown_value: 'desktop',
                            compare_label: 'current',
                        }),
                        makeStep({
                            count: 15,
                            fromBasisStep: 0.5,
                            breakdown_value: 'desktop',
                            compare_label: 'previous',
                        }),
                    ],
                }),
            ]

            it('renders two stacks per step (current, then previous), each split by breakdown value', () => {
                const result = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, options)

                expect(result).toHaveLength(2)
                expect(result.every((step) => step.bars.length === 2)).toBe(true)

                // Current stack carries the current-period value segments (nested indices 0, 2); previous
                // stack carries the previous-period segments (1, 3) — each keyed to its nested index so a
                // click resolves the right (value, period).
                const [step0] = result
                expect(
                    step0.bars[0].series.filter((s) => !s.meta?.isDropOff).map((s) => s.meta?.breakdownIndex)
                ).toEqual([0, 2])
                expect(
                    step0.bars[1].series.filter((s) => !s.meta?.isDropOff).map((s) => s.meta?.breakdownIndex)
                ).toEqual([1, 3])
            })

            it('shares the larger period’s total as the scale; the smaller stack is shorter with a blank gap', () => {
                const result = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, options)

                // basis = max(current total 100, previous total 75) = 100.
                // Step 0 current (leader) fills to 100; previous reaches its 75 entry total, 25 blank above.
                expect(stackTotal(result[0].bars[0])).toBe(100)
                expect(stackTotal(result[0].bars[1])).toBe(75)
                // Step 1 current: 30 + 20 segments, aggregate drop-off 50 → fills to 100.
                expect(result[1].bars[0].series.map((s) => s.data[0])).toEqual([30, 20, 50])
                // Step 1 previous: 15 + 15 segments, aggregate drop-off 45 → reaches its 75 entry; 25 blank.
                expect(result[1].bars[1].series.map((s) => s.data[0])).toEqual([15, 15, 45])
                // The aggregate drop-off declares each period's entry total as the interactive ceiling,
                // so the blank 25 above the previous stack is inert.
                expect(result[0].bars[0].series[2].trackData).toEqual([100])
                expect(result[0].bars[1].series[2].trackData).toEqual([75])
            })

            it('tags the aggregate drop-off so it isn’t attributed to a single value (breakdownIndex null)', () => {
                const [step0] = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, options)
                const currentDropOff = step0.bars[0].series.find((s) => s.meta?.isDropOff)

                expect(currentDropOff?.meta?.breakdownIndex).toBeNull()
                expect(currentDropOff?.visibility?.tooltip).toBe(false)
            })

            it('dims each breakdown value’s previous-period segment', () => {
                const getColor = jest.fn((v: FunnelStepWithConversionMetrics) =>
                    v.compare_label === 'previous' ? '#dimmed' : '#solid'
                )
                const [step0] = buildFunnelBarHorizontalCompareData(breakdownCompareSteps, { ...options, getColor })

                expect(step0.bars[0].series.filter((s) => !s.meta?.isDropOff).map((s) => s.color)).toEqual([
                    '#solid',
                    '#solid',
                ])
                expect(step0.bars[1].series.filter((s) => !s.meta?.isDropOff).map((s) => s.color)).toEqual([
                    '#dimmed',
                    '#dimmed',
                ])
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
        // First step of the same funnel; only the breakdown + compare drop-off path reads it.
        const firstStep = makeStep({
            count: 100,
            fromBasisStep: 1,
            name: 'Viewed',
            nested_breakdown: [
                makeStep({ count: 60, fromBasisStep: 1, breakdown_value: 'mobile' }),
                makeStep({ count: 40, fromBasisStep: 1, breakdown_value: 'desktop' }),
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
            const target = resolveFunnelBarHorizontalHover(
                { hoveredSeriesKey, seriesData, hoverPosition },
                step,
                1,
                firstStep
            )
            expect(target?.series).toEqual(expected.series)
            expect(target?.isDropOffHover).toBe(expected.isDropOffHover)
            expect(target?.color).toBe(expected.color)
        })

        describe('breakdown + compare stack drop-off', () => {
            // nested_breakdown pairs [value current, value previous, …]; the aggregate step spreads the
            // current period's totals and compare_label, so the whole-step fallback would label every
            // stack's drop-off "current" with current-period numbers.
            const compareVariant = (
                count: number,
                breakdownValue: string,
                compareLabel: 'current' | 'previous',
                droppedOffFromPrevious = 0
            ): FunnelStepWithConversionMetrics =>
                makeStep({
                    count,
                    fromBasisStep: 0,
                    breakdown_value: breakdownValue,
                    compare_label: compareLabel,
                    droppedOffFromPrevious,
                })
            const firstCompareStep = makeStep({
                count: 200,
                fromBasisStep: 1,
                compare_label: 'current',
                breakdown_value: 'mobile',
                nested_breakdown: [
                    compareVariant(120, 'mobile', 'current'),
                    compareVariant(90, 'mobile', 'previous'),
                    compareVariant(80, 'desktop', 'current'),
                    compareVariant(60, 'desktop', 'previous'),
                ],
            })
            const compareStep = makeStep({
                count: 50,
                fromBasisStep: 0.25,
                compare_label: 'current',
                breakdown_value: 'mobile',
                droppedOffFromPrevious: 50,
                nested_breakdown: [
                    compareVariant(30, 'mobile', 'current', 30),
                    compareVariant(15, 'mobile', 'previous', 30),
                    compareVariant(20, 'desktop', 'current', 20),
                    compareVariant(15, 'desktop', 'previous', 15),
                ],
            })

            // Current period: 200 first-step entrants, 100 reached this step (50 converted + 50
            // dropped); previous period: 150 first-step entrants, 75 reached (30 + 45). fromPrevious
            // and total intentionally differ so a swapped computation fails.
            it.each([
                {
                    period: 'current',
                    stackSegments: [segmentEntry(0, '#aaa'), segmentEntry(2, '#bbb')],
                    expected: { count: 50, droppedOffFromPrevious: 50, fromPrevious: 0.5, total: 0.25 },
                },
                {
                    period: 'previous',
                    stackSegments: [segmentEntry(1, '#aaa'), segmentEntry(3, '#bbb')],
                    expected: { count: 30, droppedOffFromPrevious: 45, fromPrevious: 0.4, total: 0.2 },
                },
            ])(
                'resolves the $period stack’s drop-off band to that period’s aggregate',
                ({ period, stackSegments, expected }) => {
                    const target = resolveFunnelBarHorizontalHover(
                        {
                            hoveredSeriesKey: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
                            seriesData: stackSegments,
                            hoverPosition: null,
                        },
                        compareStep,
                        1,
                        firstCompareStep
                    )

                    expect(target?.series).toEqual(
                        expect.objectContaining({
                            compare_label: period,
                            count: expected.count,
                            droppedOffFromPrevious: expected.droppedOffFromPrevious,
                            conversionRates: expect.objectContaining({
                                fromPrevious: expected.fromPrevious,
                                total: expected.total,
                            }),
                            breakdown_value: undefined,
                        })
                    )
                    expect(target?.isDropOffHover).toBe(true)
                    expect(target?.color).toBeUndefined()
                    // The band spans every breakdown value of the period, so a click opens nothing —
                    // the tooltip must not advertise one.
                    expect(target?.clickable).toBe(false)
                }
            )
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
