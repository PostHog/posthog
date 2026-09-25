import { useValues } from 'kea'

import { IconCheck, IconGear, IconHourglass } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle/LemonProgressCircle'
import { runningTimeLogic } from 'scenes/experiments/RunningTimeCalculator/runningTimeLogic'

import { Experiment } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

export function ExperimentRemainingTime({
    experiment,
    onConfigure,
}: {
    experiment: Experiment
    onConfigure: () => void
}): JSX.Element {
    const {
        remainingDays,
        currentExposures,
        targetSampleSize,
        isComplete,
        isManualMode,
        primaryMetricsResultsLoading,
    } = useValues(runningTimeLogic({ experiment }))

    const launched = isLaunched(experiment)
    const isLoading = primaryMetricsResultsLoading && !isManualMode
    const showProgress = currentExposures !== null && targetSampleSize !== null
    const days = remainingDays === null ? null : Math.ceil(remainingDays)

    let content: JSX.Element
    if (isLoading) {
        content = <span className="text-secondary">Calculating…</span>
    } else if (days === null) {
        content = <span className="text-secondary">{launched ? 'Duration pending' : 'Duration not estimated'}</span>
    } else if (isComplete) {
        content = (
            <span className="flex items-center gap-1">
                <IconCheck className="text-success" />
                <span>Target reached</span>
            </span>
        )
    } else {
        content = (
            <span className="flex items-center gap-1.5">
                {showProgress && (
                    <LemonProgressCircle progress={Math.min(currentExposures / targetSampleSize, 1)} size={16} />
                )}
                <span>{`~${days} ${days === 1 ? 'day' : 'days'} ${launched ? 'left' : 'estimated'}`}</span>
            </span>
        )
    }

    return (
        <div className="flex items-center gap-1.5" data-attr="experiment-remaining-time">
            {!showProgress && (
                <Tooltip title={launched ? 'Remaining time' : 'Estimated duration'}>
                    <IconHourglass className="text-secondary text-base shrink-0" />
                </Tooltip>
            )}
            {content}
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconGear />}
                onClick={onConfigure}
                tooltip={launched ? 'Configure target duration' : 'Estimate duration'}
                data-attr="experiment-running-time-config"
            />
        </div>
    )
}
