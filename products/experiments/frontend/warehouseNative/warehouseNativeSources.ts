import {
    type ExperimentExposureCriteria,
    type ExperimentMeanMetric,
    type ExperimentMetric,
    type ExperimentMetricSource,
    ExperimentMetricType,
    type ExperimentRatioMetric,
    type ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    type ExperimentWarehouseNativeNode,
    NodeKind,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

/** The connection and the unit. Every warehouse-native query of one experiment must share them. */
export type WarehouseNativeBinding = Pick<ExperimentWarehouseNativeNode, 'connection_id' | 'unit'>

/** A metric whose every source is a warehouse-native query. Only mean and ratio metrics accept one. */
export type WarehouseNativeMetric =
    | (ExperimentMeanMetric & { source: ExperimentWarehouseNativeNode })
    | (ExperimentRatioMetric & {
          numerator: ExperimentWarehouseNativeNode
          denominator: ExperimentWarehouseNativeNode
      })

export const EMPTY_WAREHOUSE_NATIVE_BINDING: WarehouseNativeBinding = {
    connection_id: '',
    unit: { unit_type: '', id_namespace: '' },
}

export function getWarehouseNativeExposure(
    exposureCriteria: ExperimentExposureCriteria | null | undefined
): ExperimentWarehouseNativeExposureConfig | null {
    const config = exposureCriteria?.exposure_config
    return config?.kind === NodeKind.ExperimentWarehouseNativeExposureConfig ? config : null
}

export const isWarehouseNativeSource = (
    source: { kind: NodeKind } | null | undefined
): source is ExperimentWarehouseNativeNode => source?.kind === NodeKind.ExperimentWarehouseNativeNode

export function getWarehouseNativeSources(metric: ExperimentMetric): ExperimentWarehouseNativeNode[] {
    const sources: ExperimentMetricSource[] = isExperimentMeanMetric(metric)
        ? [metric.source]
        : isExperimentRatioMetric(metric)
          ? [metric.numerator, metric.denominator]
          : []
    return sources.filter(isWarehouseNativeSource)
}

export const metricUsesWarehouseNativeSource = (metric: ExperimentMetric): boolean =>
    getWarehouseNativeSources(metric).length > 0

export function getWarehouseNativeBinding(metric: ExperimentMetric): WarehouseNativeBinding {
    const [source] = getWarehouseNativeSources(metric)
    return source ? { connection_id: source.connection_id, unit: source.unit } : EMPTY_WAREHOUSE_NATIVE_BINDING
}

export function experimentUsesWarehouseNativeSources(
    experiment: Pick<Experiment, 'exposure_criteria' | 'metrics' | 'metrics_secondary' | 'saved_metrics'>
): boolean {
    if (getWarehouseNativeExposure(experiment.exposure_criteria)) {
        return true
    }
    const queries = [
        ...(experiment.metrics ?? []),
        ...(experiment.metrics_secondary ?? []),
        ...(experiment.saved_metrics ?? []).map((savedMetric) => savedMetric?.query),
    ]
    return queries.some(
        (query) =>
            query?.kind === NodeKind.ExperimentMetric && metricUsesWarehouseNativeSource(query as ExperimentMetric)
    )
}

function toWarehouseNativeSource(
    source: ExperimentMetricSource | undefined,
    binding: WarehouseNativeBinding
): ExperimentWarehouseNativeNode {
    const base: ExperimentWarehouseNativeNode = isWarehouseNativeSource(source)
        ? source
        : {
              kind: NodeKind.ExperimentWarehouseNativeNode,
              connection_id: '',
              unit: EMPTY_WAREHOUSE_NATIVE_BINDING.unit,
              query: '',
              math: ExperimentWarehouseNativeMathType.TotalCount,
          }
    return { ...base, connection_id: binding.connection_id, unit: { ...binding.unit } }
}

/**
 * Makes every source of the metric a warehouse-native query on `binding`. A source that is already a
 * warehouse-native query keeps its SQL. A funnel or retention metric becomes a mean metric, because
 * those types cannot read a warehouse-native query.
 */
export function toWarehouseNativeMetric(
    metric: ExperimentMetric,
    binding: WarehouseNativeBinding
): WarehouseNativeMetric {
    if (isExperimentRatioMetric(metric)) {
        return {
            ...metric,
            numerator: toWarehouseNativeSource(metric.numerator, binding),
            denominator: toWarehouseNativeSource(metric.denominator, binding),
        }
    }
    if (isExperimentMeanMetric(metric)) {
        return { ...metric, source: toWarehouseNativeSource(metric.source, binding) }
    }
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: metric.uuid,
        name: metric.name,
        goal: metric.goal,
        metric_type: ExperimentMetricType.MEAN,
        source: toWarehouseNativeSource(undefined, binding),
    }
}

/**
 * Copies the exposure's connection and unit onto the warehouse-native metrics. The API rejects an
 * exposure that differs from the metrics, so a changed exposure must save together with them.
 * A metric that needs no change keeps its identity.
 */
export function alignMetricsWithExposure<T extends { kind: NodeKind }>(
    metrics: T[],
    exposure: WarehouseNativeBinding
): T[] {
    return metrics.map((metric) => {
        if (metric.kind !== NodeKind.ExperimentMetric) {
            return metric
        }
        const experimentMetric = metric as unknown as ExperimentMetric
        const aligned = getWarehouseNativeSources(experimentMetric).every(
            (source) =>
                source.connection_id === exposure.connection_id &&
                source.unit.unit_type === exposure.unit.unit_type &&
                source.unit.id_namespace === exposure.unit.id_namespace
        )
        return aligned ? metric : (toWarehouseNativeMetric(experimentMetric, exposure) as unknown as T)
    })
}

const getBindingError = (binding: WarehouseNativeBinding): string | null => {
    if (!binding.connection_id) {
        return 'Select a BigQuery connection'
    }
    if (!binding.unit.unit_type.trim()) {
        return 'Enter the randomization unit'
    }
    if (!binding.unit.id_namespace.trim()) {
        return 'Enter the ID type'
    }
    return null
}

export function getWarehouseNativeExposureError(config: ExperimentWarehouseNativeExposureConfig): string | null {
    return getBindingError(config) ?? (config.query.trim() ? null : 'Enter the exposure query')
}

/** Why the metric cannot be saved yet, or null when its warehouse-native queries are complete. */
export function getWarehouseNativeMetricError(metric: ExperimentMetric): string | null {
    for (const source of getWarehouseNativeSources(metric)) {
        const bindingError = getBindingError(source)
        if (bindingError) {
            return bindingError
        }
        if (!source.query.trim()) {
            return 'Enter a SQL query for every source'
        }
        if (source.math === ExperimentWarehouseNativeMathType.Sum && !source.math_property?.trim()) {
            return 'Enter the column to sum'
        }
    }
    return null
}
