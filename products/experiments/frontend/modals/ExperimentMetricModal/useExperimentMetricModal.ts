import { useActions, useValues } from 'kea'

import { exposureCriteriaModalLogic } from 'scenes/experiments/ExperimentView/exposureCriteriaModalLogic'
import { getMetricIncompleteReason } from 'scenes/experiments/utils'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'

import {
    alignMetricsWithExposure,
    getWarehouseNativeExposure,
    getWarehouseNativeMetricError,
} from 'products/experiments/frontend/warehouseNative/warehouseNativeSources'

import { type MetricContext, experimentMetricModalLogic } from './experimentMetricModalLogic'

export const DELETE_METRIC_TITLE = 'Delete this metric?'
export const DELETE_METRIC_WARNING = 'This action cannot be undone.'

export interface ExperimentMetricModalModel {
    isOpen: boolean
    metric: ExperimentMetric | null
    context: MetricContext
    isCreateMode: boolean
    isEditMode: boolean
    title: string
    saveLabel: string
    close: () => void
    setMetric: (metric: ExperimentMetric) => void
    openExposureCriteriaModal: (exposureCriteria?: ExperimentExposureCriteria) => void
    metricToSave: ExperimentMetric | null
    saveDisabledReason: string | null | undefined
}

export function useExperimentMetricModal(
    exposureCriteria: ExperimentExposureCriteria | undefined
): ExperimentMetricModalModel {
    const { isModalOpen, metric, context, isCreateMode, isEditMode } = useValues(experimentMetricModalLogic)
    const { closeExperimentMetricModal, setMetric } = useActions(experimentMetricModalLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)

    // The exposure can change while this modal is open, and the API rejects a metric on another connection or unit
    const warehouseExposure = getWarehouseNativeExposure(exposureCriteria)
    const metricToSave = metric
        ? warehouseExposure
            ? alignMetricsWithExposure([metric], warehouseExposure)[0]
            : metric
        : null

    return {
        isOpen: isModalOpen,
        metric,
        context,
        isCreateMode,
        isEditMode,
        title: isCreateMode ? 'Create experiment metric' : 'Edit experiment metric',
        saveLabel: isCreateMode ? 'Create' : 'Save',
        close: closeExperimentMetricModal,
        setMetric,
        openExposureCriteriaModal,
        metricToSave,
        saveDisabledReason: metricToSave
            ? (getWarehouseNativeMetricError(metricToSave) ?? getMetricIncompleteReason(metricToSave))
            : undefined,
    }
}
