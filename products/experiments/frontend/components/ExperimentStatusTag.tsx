import { Tooltip } from '@posthog/lemon-ui'

import { StatusTag } from 'products/experiments/frontend/components/StatusTag'
import {
    EXPERIMENT_PAUSED_TOOLTIP,
    type ExperimentStatusInput,
    getExperimentStatus,
    isExperimentPaused,
} from 'products/experiments/frontend/experimentStatus'

export function ExperimentStatusTag({ experiment }: { experiment: ExperimentStatusInput }): JSX.Element {
    const status = getExperimentStatus(experiment)

    if (isExperimentPaused(experiment)) {
        return (
            <Tooltip title={EXPERIMENT_PAUSED_TOOLTIP}>
                <StatusTag status={status} />
            </Tooltip>
        )
    }

    return <StatusTag status={status} />
}
