import { IconWarning } from '@posthog/icons'
import { LemonModal, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillMetricSourceModal } from './QuillMetricSourceModal'
import {
    METRIC_SOURCE_DOCS_URL,
    METRIC_SOURCE_OPTIONS,
    type MetricSourceExperiment,
    useMetricSourceModal,
} from './useMetricSourceModal'

export const MetricSourceModal = ({
    experiment,
}: {
    /** The experiment that receives the metric. The wizard passes its draft, which `experimentLogic` does not hold. */
    experiment: MetricSourceExperiment
}): JSX.Element | null => {
    const { isOpen, close, pickSingleUse, pickShared, warning } = useMetricSourceModal(experiment)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav && resultsRedesign) {
        return (
            <QuillMetricSourceModal
                isOpen={isOpen}
                close={close}
                pickSingleUse={pickSingleUse}
                pickShared={pickShared}
                warning={warning}
            />
        )
    }

    return (
        <LemonModal isOpen={isOpen} onClose={close} width={1000} title="Choose metric source">
            <div className="flex gap-4 mb-4">
                <div className="flex-1 cursor-pointer p-4 rounded border hover:border-accent" onClick={pickSingleUse}>
                    <div className="font-semibold">
                        <span>{METRIC_SOURCE_OPTIONS.singleUse.title}</span>
                    </div>
                    <div className="text-secondary text-sm leading-relaxed">
                        {METRIC_SOURCE_OPTIONS.singleUse.description}
                    </div>
                </div>
                <div className="flex-1 cursor-pointer p-4 rounded border hover:border-accent" onClick={pickShared}>
                    <div className="font-semibold">
                        <span>{METRIC_SOURCE_OPTIONS.shared.title}</span>
                    </div>
                    <div className="text-secondary text-sm leading-relaxed">
                        {METRIC_SOURCE_OPTIONS.shared.description}
                    </div>
                </div>
            </div>
            {warning && (
                <div className="flex items-center gap-2 p-3 rounded bg-warning-highlight text-sm">
                    <IconWarning className="text-warning text-lg shrink-0" />
                    <p className="mb-0">
                        {warning}
                        <Link to={METRIC_SOURCE_DOCS_URL} target="_blank">
                            Learn more
                        </Link>
                    </p>
                </div>
            )}
        </LemonModal>
    )
}
