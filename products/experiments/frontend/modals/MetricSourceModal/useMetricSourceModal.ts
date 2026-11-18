import { useActions, useValues } from 'kea'

import { getDefaultFunnelMetric } from 'scenes/experiments/utils'

import type { Experiment } from '~/types'

import { experimentMetricModalLogic } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { sharedMetricModalLogic } from 'products/experiments/frontend/modals/SharedMetricModal/sharedMetricModalLogic'
import {
    getWarehouseNativeExposure,
    toWarehouseNativeMetric,
} from 'products/experiments/frontend/warehouseNative/warehouseNativeSources'

import { metricSourceModalLogic } from './metricSourceModalLogic'

const METRIC_COUNT_WARNING_THRESHOLD = 3

export const METRIC_SOURCE_DOCS_URL = 'https://posthog.com/docs/experiments/best-practices'
export const METRIC_SOURCE_OPTIONS = {
    singleUse: { title: 'Single-use', description: 'Create a new metric specific to this experiment.' },
    shared: { title: 'Shared', description: 'Use a pre-configured metric that can be reused across experiments.' },
}

export type MetricSourceExperiment = Pick<
    Experiment,
    'metrics' | 'metrics_secondary' | 'start_date' | 'exposure_criteria'
>

export function useMetricSourceModal(experiment: MetricSourceExperiment): {
    isOpen: boolean
    close: () => void
    pickSingleUse: () => void
    pickShared: () => void
    warning: string | null
} {
    const { isModalOpen, context } = useValues(metricSourceModalLogic)
    const { closeMetricSourceModal } = useActions(metricSourceModalLogic)
    const { openExperimentMetricModal, setMetric } = useActions(experimentMetricModalLogic)
    const { openSharedMetricModal } = useActions(sharedMetricModalLogic)

    const metricCount =
        context.field === 'metrics' ? (experiment.metrics?.length ?? 0) : (experiment.metrics_secondary?.length ?? 0)
    const isRunning = !!experiment.start_date
    const manyMetrics = metricCount >= METRIC_COUNT_WARNING_THRESHOLD

    return {
        isOpen: isModalOpen,
        close: closeMetricSourceModal,
        pickSingleUse: () => {
            closeMetricSourceModal()
            openExperimentMetricModal(context)
            // An experiment with a warehouse-native exposure accepts warehouse-native metrics only
            const warehouseExposure = getWarehouseNativeExposure(experiment.exposure_criteria)
            if (warehouseExposure) {
                setMetric(toWarehouseNativeMetric(getDefaultFunnelMetric(), warehouseExposure))
            }
        },
        pickShared: () => {
            closeMetricSourceModal()
            openSharedMetricModal(context)
        },
        warning:
            isRunning && manyMetrics
                ? 'This experiment is already running and has several metrics. Choosing what to measure after seeing data can bias your results. '
                : isRunning
                  ? 'This experiment is already running. Choosing what to measure after seeing data can bias your results. '
                  : manyMetrics
                    ? 'Each additional metric is another result to interpret. Make sure each has a clear hypothesis. '
                    : null,
    }
}
