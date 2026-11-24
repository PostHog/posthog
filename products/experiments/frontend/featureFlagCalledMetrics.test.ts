import {
    type ExperimentMetric,
    ExperimentMetricType,
    type ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { featureFlagCalledMetricNames } from './featureFlagCalledMetrics'

const flagCalled = { kind: NodeKind.EventsNode, event: '$feature_flag_called' }
const pageview = { kind: NodeKind.EventsNode, event: '$pageview' }

const metric = (fields: Record<string, unknown>): ExperimentMetric =>
    ({ kind: NodeKind.ExperimentMetric, ...fields }) as unknown as ExperimentMetric

const experimentWith = (fields: Partial<Experiment>): Experiment =>
    ({ metrics: [], metrics_secondary: [], saved_metrics: [], ...fields }) as Experiment

describe('featureFlagCalledMetricNames', () => {
    it.each<{ name: string; experiment: Experiment; expected: string[] }>([
        {
            name: 'a mean metric source',
            experiment: experimentWith({
                metrics: [metric({ metric_type: ExperimentMetricType.MEAN, name: 'Flag calls', source: flagCalled })],
            }),
            expected: ['Flag calls'],
        },
        {
            name: 'a later funnel step of an unnamed metric',
            experiment: experimentWith({
                metrics: [metric({ metric_type: ExperimentMetricType.FUNNEL, series: [pageview, flagCalled] })],
            }),
            expected: ['$pageview'],
        },
        {
            name: 'a ratio denominator in a secondary metric',
            experiment: experimentWith({
                metrics_secondary: [
                    metric({
                        metric_type: ExperimentMetricType.RATIO,
                        name: 'Ratio',
                        numerator: pageview,
                        denominator: flagCalled,
                    }),
                ],
            }),
            expected: ['Ratio'],
        },
        {
            name: 'a retention completion event',
            experiment: experimentWith({
                metrics: [
                    metric({
                        metric_type: ExperimentMetricType.RETENTION,
                        name: 'Retention',
                        start_event: { kind: NodeKind.ExperimentExposureNode },
                        completion_event: flagCalled,
                    }),
                ],
            }),
            expected: ['Retention'],
        },
        {
            name: 'the effective query of a shared metric',
            experiment: experimentWith({
                saved_metrics: [
                    {
                        name: 'Shared flag calls',
                        metadata: { type: 'primary' },
                        query: metric({ metric_type: ExperimentMetricType.MEAN, source: pageview }),
                        effective_query: metric({ metric_type: ExperimentMetricType.MEAN, source: flagCalled }),
                    },
                ],
            }),
            expected: ['Shared flag calls'],
        },
        {
            name: 'no metric when only other events, actions and legacy queries are used',
            experiment: experimentWith({
                metrics: [
                    metric({ metric_type: ExperimentMetricType.MEAN, source: { kind: NodeKind.ActionsNode, id: 1 } }),
                    metric({
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: '$experiment_exposure' },
                    }),
                    {
                        kind: NodeKind.ExperimentTrendsQuery,
                        count_query: { kind: NodeKind.TrendsQuery, series: [flagCalled] },
                    } as unknown as ExperimentTrendsQuery,
                ],
            }),
            expected: [],
        },
    ])('finds $name', ({ experiment, expected }) => {
        expect(featureFlagCalledMetricNames(experiment)).toEqual(expected)
    })
})
