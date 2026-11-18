import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { MetricConversionWindow } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricConversionWindow'
import { MetricEventDetails } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricEventDetails'
import { MetricGoal } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricGoal'
import { MetricOutlierHandling } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricOutlierHandling'
import { MetricStepOrder } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricStepOrder'
import { MetricTypeTag } from 'scenes/experiments/MetricsView/shared/MetricTypeTag'
import { getDefaultMetricTitle } from 'scenes/experiments/MetricsView/shared/utils'
import { urls } from 'scenes/urls'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { QuillSharedMetricDetailsModal } from './QuillSharedMetricDetailsModal'
import { useSharedMetricDetailsModal } from './useSharedMetricDetailsModal'

function MetricSummary({ metric }: { metric: ExperimentMetric }): JSX.Element | null {
    if (!metric.sharedMetricId) {
        return null
    }

    return (
        <div className="border rounded bg-surface-primary p-4">
            <div className="space-y-3">
                <div className="flex-1 min-w-0 gap-2">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-sm break-words">
                            {metric.name || getDefaultMetricTitle(metric)}
                        </span>
                        <Link
                            target="_blank"
                            className="font-semibold flex items-center"
                            to={urls.experimentsSharedMetric(metric.sharedMetricId)}
                        >
                            <IconOpenInNew fontSize="18" />
                        </Link>
                    </div>
                    <MetricEventDetails metric={metric} />
                    <div className="flex items-center mt-2 gap-1">
                        <MetricTypeTag metric={metric} />
                        <LemonTag type="option" size="small">
                            Shared metric
                        </LemonTag>
                    </div>
                </div>

                <div className="border-t border-border" />

                <div className="space-y-1">
                    <MetricGoal metric={metric} />
                    <MetricConversionWindow metric={metric} />
                    <MetricStepOrder metric={metric} />
                    <MetricOutlierHandling metric={metric} />
                </div>
            </div>
        </div>
    )
}

export function SharedMetricDetailsModal({
    onDelete,
}: {
    onDelete: (sharedMetricId: number, context: MetricContext) => void
}): JSX.Element | null {
    const { sharedMetric, isOpen, close, remove } = useSharedMetricDetailsModal(onDelete)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!sharedMetric) {
        return null
    }

    if (todayRailNav && resultsRedesign) {
        return (
            <QuillSharedMetricDetailsModal sharedMetric={sharedMetric} isOpen={isOpen} close={close} remove={remove} />
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={close}
            maxWidth={800}
            title="Shared metric"
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {sharedMetric && (
                            <LemonButton status="danger" onClick={remove} type="secondary">
                                Remove from experiment
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton onClick={close} type="secondary">
                            Close
                        </LemonButton>
                    </div>
                </div>
            }
        >
            {sharedMetric && <MetricSummary metric={sharedMetric} />}
        </LemonModal>
    )
}
