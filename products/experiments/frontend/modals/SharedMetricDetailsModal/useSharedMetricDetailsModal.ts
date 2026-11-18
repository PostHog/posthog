import { useActions, useValues } from 'kea'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { sharedMetricDetailsModalLogic } from './sharedMetricDetailsModalLogic'

export function useSharedMetricDetailsModal(onDelete: (sharedMetricId: number, context: MetricContext) => void): {
    sharedMetric: ExperimentMetric | null
    isOpen: boolean
    close: () => void
    remove: () => void
} {
    const { isModalOpen, sharedMetric, context } = useValues(sharedMetricDetailsModalLogic)
    const { closeSharedMetricDetailModal } = useActions(sharedMetricDetailsModalLogic)

    return {
        sharedMetric: sharedMetric && sharedMetric.sharedMetricId ? sharedMetric : null,
        isOpen: isModalOpen,
        close: closeSharedMetricDetailModal,
        remove: () => {
            if (!sharedMetric?.sharedMetricId) {
                return
            }
            onDelete(sharedMetric.sharedMetricId, context)
            closeSharedMetricDetailModal()
        },
    }
}
