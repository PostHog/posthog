import { render } from '@testing-library/react'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import {
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric,
    ExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricGoal, FunnelConversionWindowTimeUnit, StepOrderValue } from '~/types'

import { getMetricChanges } from './metricChangeDescriptions'

describe('metric-change-descriptions', () => {
    // Helper factory functions to create test metrics
    const createBaseMeanMetric = (overrides?: Partial<ExperimentMeanMetric>): ExperimentMeanMetric => ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        fingerprint: 'test-fingerprint',
        name: 'Test Metric',
        source: {
            kind: NodeKind.EventsNode,
            event: 'test_event',
        },
        ...overrides,
    })

    const createBaseFunnelMetric = (overrides?: Partial<ExperimentFunnelMetric>): ExperimentFunnelMetric => ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.FUNNEL,
        fingerprint: 'test-fingerprint',
        name: 'Test Funnel',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: 'step1',
            },
            {
                kind: NodeKind.EventsNode,
                event: 'step2',
            },
        ],
        ...overrides,
    })

    const createBaseRatioMetric = (overrides?: Partial<ExperimentRatioMetric>): ExperimentRatioMetric => ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.RATIO,
        fingerprint: 'test-fingerprint',
        name: 'Test Ratio',
        numerator: {
            kind: NodeKind.EventsNode,
            event: 'numerator_event',
        },
        denominator: {
            kind: NodeKind.EventsNode,
            event: 'denominator_event',
        },
        ...overrides,
    })

    describe('getMetricChanges', () => {
        describe('array length changes', () => {
            it('detects when a metric is added', () => {
                const before: ExperimentMetric[] = [createBaseMeanMetric()]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric(),
                    createBaseMeanMetric({ fingerprint: 'new-metric' }),
                ]

                const result = getMetricChanges(before, after)
                expect(result).toBe('added a metric to')
            })

            it('detects when a metric is removed', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric(),
                    createBaseMeanMetric({ fingerprint: 'extra-metric' }),
                ]
                const after: ExperimentMetric[] = [createBaseMeanMetric()]

                const result = getMetricChanges(before, after)
                expect(result).toBe('removed a metric from')
            })

            it('returns null when arrays are empty', () => {
                const result = getMetricChanges([], [])
                expect(result).toBeNull()
            })
        })

        describe('fingerprint-based matching', () => {
            it('returns null when no metric was changed (same fingerprints)', () => {
                const before: ExperimentMetric[] = [createBaseMeanMetric()]
                const after: ExperimentMetric[] = [createBaseMeanMetric()]

                const result = getMetricChanges(before, after)
                expect(result).toBeNull()
            })

            it('returns null when only fingerprint changed', () => {
                const before: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'old-fingerprint' })]
                const after: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'new-fingerprint' })]

                const result = getMetricChanges(before, after)
                expect(result).toBeNull()
            })

            it('detects changes when fingerprint and other properties changed', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'old-fingerprint', goal: ExperimentMetricGoal.Increase }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'new-fingerprint', goal: ExperimentMetricGoal.Decrease }),
                ]

                const result = getMetricChanges(before, after)
                expect(result).not.toBeNull()
                expect(Array.isArray(result)).toBe(true)
            })
        })

        describe('metric type changes', () => {
            it('detects metric type change and renders JSX', () => {
                const before: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'old' })]
                const after: ExperimentMetric[] = [createBaseFunnelMetric({ fingerprint: 'new', name: 'Test Metric' })]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const { container } = render(<>{result[0]}</>)
                    expect(container.textContent).toContain('changed the type from')
                    expect(container.textContent).toContain('mean')
                    expect(container.textContent).toContain('funnel')
                }
            })
        })

        describe('goal changes', () => {
            it('detects goal change and renders JSX', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'old', goal: ExperimentMetricGoal.Increase }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'new', goal: ExperimentMetricGoal.Decrease }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const { container } = render(<>{result[0]}</>)
                    expect(container.textContent).toContain('set the goal')
                    expect(container.textContent).toContain('decrease')
                }
            })

            it('does not detect goal change when goal is the same', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'old', goal: ExperimentMetricGoal.Increase }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({ fingerprint: 'new', goal: ExperimentMetricGoal.Increase }),
                ]

                const result = getMetricChanges(before, after)
                // Should return null because only fingerprint changed
                expect(result).toBeNull()
            })
        })

        describe('conversion window changes', () => {
            it.each([
                {
                    name: 'detects conversion window removal',
                    before: { conversion_window: 7, conversion_window_unit: FunnelConversionWindowTimeUnit.Day },
                    after: {},
                    expectedText: 'set the conversion window to the experiment duration',
                },
                {
                    name: 'detects conversion window addition',
                    before: {},
                    after: { conversion_window: 14, conversion_window_unit: FunnelConversionWindowTimeUnit.Day },
                    expectedText: 'set the conversion window to 14 day',
                },
            ])('$name', (testCase) => {
                const before: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'old', ...testCase.before })]
                const after: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'new', ...testCase.after })]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    expect(text.some((t) => t?.includes(testCase.expectedText))).toBe(true)
                }
            })
        })

        describe('funnel-specific changes', () => {
            it('detects funnel order type change', () => {
                const before: ExperimentMetric[] = [
                    createBaseFunnelMetric({ fingerprint: 'old', funnel_order_type: StepOrderValue.ORDERED }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseFunnelMetric({ fingerprint: 'new', funnel_order_type: StepOrderValue.UNORDERED }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    expect(text.some((t) => t?.includes('set the step order to unordered'))).toBe(true)
                }
            })

            it('detects funnel series change', () => {
                const before: ExperimentMetric[] = [
                    createBaseFunnelMetric({
                        fingerprint: 'old',
                        series: [{ kind: NodeKind.EventsNode, event: 'step1' }],
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseFunnelMetric({
                        fingerprint: 'new',
                        series: [{ kind: NodeKind.EventsNode, event: 'step2' }],
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    expect(text.some((t) => t?.includes('changed the funnel series'))).toBe(true)
                }
            })
        })

        describe('mean-specific changes', () => {
            it('detects source event change', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'old',
                        source: { kind: NodeKind.EventsNode, event: 'old_event' },
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'new',
                        source: { kind: NodeKind.EventsNode, event: 'new_event' },
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    expect(text.some((t) => t?.includes('changed the source event'))).toBe(true)
                }
            })

            describe('outlier handling changes', () => {
                it.each([
                    {
                        name: 'detects outlier handling bounds removal',
                        before: { upper_bound_percentile: 95, lower_bound_percentile: 5 },
                        after: {},
                        expectedText: 'removed the outlier handling lower and upper bounds',
                    },
                    {
                        name: 'detects outlier handling bounds addition',
                        before: {},
                        after: { upper_bound_percentile: 95, lower_bound_percentile: 5 },
                        expectedText:
                            'set the outlier handling lower bound percentile to 5 and upper bound percentile to 95',
                    },
                    {
                        name: 'detects lower bound removal',
                        before: { upper_bound_percentile: 95, lower_bound_percentile: 5 },
                        after: { upper_bound_percentile: 95 },
                        expectedText: 'removed the outlier handling lower bound percentile',
                    },
                    {
                        name: 'detects upper bound removal',
                        before: { upper_bound_percentile: 95, lower_bound_percentile: 5 },
                        after: { lower_bound_percentile: 5 },
                        expectedText: 'removed the outlier handling upper bound percentile',
                    },
                    {
                        name: 'detects lower bound change only',
                        before: { lower_bound_percentile: 5 },
                        after: { lower_bound_percentile: 1 },
                        expectedText: 'set the outlier handling lower bound percentile to 1',
                    },
                    {
                        name: 'detects upper bound change only',
                        before: { upper_bound_percentile: 95 },
                        after: { upper_bound_percentile: 99 },
                        expectedText: 'set the outlier handling upper bound percentile to 99',
                    },
                ])('$name', (testCase) => {
                    const before: ExperimentMetric[] = [
                        createBaseMeanMetric({ fingerprint: 'old', ...testCase.before }),
                    ]
                    const after: ExperimentMetric[] = [createBaseMeanMetric({ fingerprint: 'new', ...testCase.after })]

                    const result = getMetricChanges(before, after)
                    expect(Array.isArray(result)).toBe(true)
                    if (Array.isArray(result)) {
                        const text = result.map((item) =>
                            typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                        )
                        expect(text.some((t) => t?.includes(testCase.expectedText))).toBe(true)
                    }
                })
            })
        })

        describe('ratio-specific changes', () => {
            it.each([
                {
                    name: 'detects numerator change only',
                    numeratorBefore: { kind: NodeKind.EventsNode, event: 'old_numerator' },
                    numeratorAfter: { kind: NodeKind.EventsNode, event: 'new_numerator' },
                    denominatorBefore: { kind: NodeKind.EventsNode, event: 'denominator' },
                    denominatorAfter: { kind: NodeKind.EventsNode, event: 'denominator' },
                    expectedText: 'changed the numerator',
                    notExpectedText: 'denominator',
                },
                {
                    name: 'detects denominator change only',
                    numeratorBefore: { kind: NodeKind.EventsNode, event: 'numerator' },
                    numeratorAfter: { kind: NodeKind.EventsNode, event: 'numerator' },
                    denominatorBefore: { kind: NodeKind.EventsNode, event: 'old_denominator' },
                    denominatorAfter: { kind: NodeKind.EventsNode, event: 'new_denominator' },
                    expectedText: 'changed the denominator',
                    notExpectedText: 'changed the numerator and denominator',
                },
                {
                    name: 'detects both numerator and denominator change',
                    numeratorBefore: { kind: NodeKind.EventsNode, event: 'old_numerator' },
                    numeratorAfter: { kind: NodeKind.EventsNode, event: 'new_numerator' },
                    denominatorBefore: { kind: NodeKind.EventsNode, event: 'old_denominator' },
                    denominatorAfter: { kind: NodeKind.EventsNode, event: 'new_denominator' },
                    expectedText: 'changed the numerator and denominator',
                },
            ])('$name', (testCase) => {
                const before: ExperimentMetric[] = [
                    createBaseRatioMetric({
                        fingerprint: 'old',
                        numerator: testCase.numeratorBefore as any,
                        denominator: testCase.denominatorBefore as any,
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseRatioMetric({
                        fingerprint: 'new',
                        numerator: testCase.numeratorAfter as any,
                        denominator: testCase.denominatorAfter as any,
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    expect(text.some((t) => t?.includes(testCase.expectedText))).toBe(true)
                    if (testCase.notExpectedText) {
                        expect(text.some((t) => t?.includes(testCase.notExpectedText))).toBe(false)
                    }
                }
            })
        })

        describe('multiple simultaneous changes', () => {
            it('detects multiple changes in one edit', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'old',
                        goal: ExperimentMetricGoal.Increase,
                        source: { kind: NodeKind.EventsNode, event: 'old_event' },
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'new',
                        goal: ExperimentMetricGoal.Decrease,
                        source: { kind: NodeKind.EventsNode, event: 'new_event' },
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const text = result.map((item) =>
                        typeof item === 'string' ? item : render(<>{item}</>).container.textContent
                    )
                    // Should detect both goal and source event changes
                    expect(text.some((t) => t?.includes('set the goal'))).toBe(true)
                    expect(text.some((t) => t?.includes('changed the source event'))).toBe(true)
                }
            })
        })

        describe('metric naming in output', () => {
            it('includes custom metric name in output', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'old',
                        name: 'Custom Metric Name',
                        goal: ExperimentMetricGoal.Increase,
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'new',
                        name: 'Custom Metric Name',
                        goal: ExperimentMetricGoal.Decrease,
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const lastElement = result[result.length - 1]
                    const { container } = render(<>{lastElement}</>)
                    expect(container.textContent).toContain('Custom Metric Name')
                    expect(container.textContent).toContain('for the metric')
                }
            })

            it('uses default metric title when name is not provided', () => {
                const before: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'old',
                        name: undefined,
                        goal: ExperimentMetricGoal.Increase,
                        source: { kind: NodeKind.EventsNode, event: 'test_event' },
                    }),
                ]
                const after: ExperimentMetric[] = [
                    createBaseMeanMetric({
                        fingerprint: 'new',
                        name: undefined,
                        goal: ExperimentMetricGoal.Decrease,
                        source: { kind: NodeKind.EventsNode, event: 'test_event' },
                    }),
                ]

                const result = getMetricChanges(before, after)
                expect(Array.isArray(result)).toBe(true)
                if (Array.isArray(result)) {
                    const lastElement = result[result.length - 1]
                    const { container } = render(<>{lastElement}</>)
                    // Should use the event name as default title
                    expect(container.textContent).toContain('test_event')
                }
            })
        })

        describe('edge cases', () => {
            it('handles empty before array', () => {
                const after: ExperimentMetric[] = [createBaseMeanMetric()]
                const result = getMetricChanges([], after)
                expect(result).toBe('added a metric to')
            })

            it('handles empty after array', () => {
                const before: ExperimentMetric[] = [createBaseMeanMetric()]
                const result = getMetricChanges(before, [])
                expect(result).toBe('removed a metric from')
            })

            it('returns null when metrics are identical except for expected differences', () => {
                const metric = createBaseMeanMetric()
                const result = getMetricChanges([metric], [metric])
                expect(result).toBeNull()
            })
        })
    })
})
