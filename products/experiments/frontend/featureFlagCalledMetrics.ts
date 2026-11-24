import { getDefaultMetricTitle } from 'scenes/experiments/MetricsView/shared/utils'
import { type ExperimentSavedMetric, sharedMetricEffectiveQuery } from 'scenes/experiments/utils'
import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/flagEvaluationsTable'

import { type ExperimentMetric, ExperimentMetricType, type NodeKind } from '~/queries/schema/schema-general'
import { isExperimentMetric } from '~/queries/utils'
import type { Experiment } from '~/types'

function metricNodes(metric: ExperimentMetric): { kind: NodeKind; event?: string | null }[] {
    switch (metric.metric_type) {
        case ExperimentMetricType.MEAN:
        case ExperimentMetricType.QUANTILE:
            return [metric.source]
        case ExperimentMetricType.FUNNEL:
            return metric.series
        case ExperimentMetricType.RATIO:
            return [metric.numerator, metric.denominator]
        case ExperimentMetricType.RETENTION:
            return [metric.start_event, metric.completion_event]
        default:
            return []
    }
}

function readsFeatureFlagCalled(metric: ExperimentMetric): boolean {
    return metricNodes(metric).some((node) => node.event === FEATURE_FLAG_CALLED_EVENT)
}

// An action step that matches the event is not found, because the experiment does not carry action definitions.
export function featureFlagCalledMetricNames(experiment: Experiment): string[] {
    const inlineMetrics = [...(experiment.metrics || []), ...(experiment.metrics_secondary || [])].map((metric) => ({
        metric,
        name: metric.name,
    }))
    const sharedMetrics = ((experiment.saved_metrics || []) as ExperimentSavedMetric[]).map((sharedMetric) => ({
        metric: sharedMetricEffectiveQuery(sharedMetric),
        name: sharedMetric.name,
    }))
    return [...inlineMetrics, ...sharedMetrics].flatMap(({ metric, name }) =>
        isExperimentMetric(metric) && readsFeatureFlagCalled(metric) ? [name || getDefaultMetricTitle(metric)] : []
    )
}
