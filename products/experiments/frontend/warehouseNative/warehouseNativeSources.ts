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

export type MetricDataSources = { warehouseNative: boolean; posthog: boolean }

/** Which data sources the metric queries read. A query of another kind than `ExperimentMetric` reads PostHog data. */
export function getMetricDataSources(queries: ({ kind: NodeKind } | null | undefined)[]): MetricDataSources {
    const present = queries.filter((query): query is { kind: NodeKind } => !!query)
    const warehouseNative = present.filter(
        (query) =>
            query.kind === NodeKind.ExperimentMetric && metricUsesWarehouseNativeSource(query as ExperimentMetric)
    )
    return { warehouseNative: warehouseNative.length > 0, posthog: warehouseNative.length < present.length }
}

/**
 * Which data sources the metrics of the experiment read, shared metrics included. The API accepts
 * warehouse-native metrics only under a warehouse-native exposure, and no other metric under one.
 */
export function getExperimentMetricDataSources(
    experiment: Pick<Experiment, 'metrics' | 'metrics_secondary' | 'saved_metrics'>
): MetricDataSources {
    return getMetricDataSources([
        ...(experiment.metrics ?? []),
        ...(experiment.metrics_secondary ?? []),
        ...(experiment.saved_metrics ?? []).map((savedMetric) => savedMetric?.query),
    ])
}

/**
 * Why the exposure cannot change to the other data source. The API rejects an exposure that reads
 * another data source than the metrics, so the metrics must go first.
 */
export function getExposureSourceBlockedReasons(
    exposureIsWarehouseNative: boolean,
    metricDataSources: MetricDataSources
): { warehouseNative?: string; posthog?: string } {
    return {
        warehouseNative:
            !exposureIsWarehouseNative && metricDataSources.posthog
                ? "Remove this experiment's metrics first. A warehouse-native exposure only works with warehouse-native metrics."
                : undefined,
        posthog:
            exposureIsWarehouseNative && metricDataSources.warehouseNative
                ? "Remove this experiment's metrics first. Warehouse-native metrics only work with a warehouse-native exposure."
                : undefined,
    }
}

export function experimentUsesWarehouseNativeSources(
    experiment: Pick<Experiment, 'exposure_criteria' | 'metrics' | 'metrics_secondary' | 'saved_metrics'>
): boolean {
    return (
        !!getWarehouseNativeExposure(experiment.exposure_criteria) ||
        getExperimentMetricDataSources(experiment).warehouseNative
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

const metricMatchesBinding = (metric: ExperimentMetric, binding: WarehouseNativeBinding): boolean =>
    getWarehouseNativeSources(metric).every(
        (source) =>
            source.connection_id === binding.connection_id &&
            source.unit.unit_type === binding.unit.unit_type &&
            source.unit.id_namespace === binding.unit.id_namespace
    )

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
        return metricMatchesBinding(experimentMetric, exposure)
            ? metric
            : (toWarehouseNativeMetric(experimentMetric, exposure) as unknown as T)
    })
}

/**
 * Why the API would reject the exposure together with the metrics, or null. A shared metric keeps
 * its own connection and unit, so `alignMetricsWithExposure` cannot move it to a changed exposure.
 */
export function getWarehouseNativeMismatchError(
    exposure: ExperimentWarehouseNativeExposureConfig | null,
    metricDataSources: MetricDataSources,
    sharedMetricQueries: ({ kind: NodeKind } | null | undefined)[]
): string | null {
    if (!exposure) {
        return metricDataSources.warehouseNative
            ? 'Warehouse-native metrics need a warehouse-native exposure. Remove them, or change the exposure.'
            : null
    }
    if (metricDataSources.posthog) {
        return 'A warehouse-native exposure only works with warehouse-native metrics. Remove the other metrics, or change the exposure.'
    }
    const sharedMetricDiffers = sharedMetricQueries.some(
        (query) =>
            query?.kind === NodeKind.ExperimentMetric && !metricMatchesBinding(query as ExperimentMetric, exposure)
    )
    return sharedMetricDiffers
        ? 'A shared metric uses another connection, unit or ID type than the exposure. Remove it, or match the exposure to it.'
        : null
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
