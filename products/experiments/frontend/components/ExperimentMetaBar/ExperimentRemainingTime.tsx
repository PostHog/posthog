import { useValues } from 'kea'

import { IconCheck, IconGear, IconHourglass, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle/LemonProgressCircle'
import {
    MINIMUM_DETECTABLE_EFFECT_MAX,
    roundUpDetectableEffect,
} from 'scenes/experiments/RunningTimeCalculator/calculations'
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
    const { remainingDays, currentExposures, targetSampleSize, isComplete, isCalculating, outlook, targetEffect } =
        useValues(runningTimeLogic({ experiment }))

    const launched = isLaunched(experiment)
    const showProgress = currentExposures !== null && targetSampleSize !== null
    const days = remainingDays === null ? null : Math.ceil(remainingDays)

    let content: JSX.Element
    if (isCalculating) {
        content = <span className="text-secondary">Calculating…</span>
    } else if (days === null) {
        content = <span className="text-secondary">{launched ? 'Duration pending' : 'No duration estimate'}</span>
    } else if (isComplete) {
        content = (
            <span className="flex items-center gap-1">
                <IconCheck className="text-success" />
                <span>Target reached</span>
            </span>
        )
    } else if (outlook?.isOutOfReach) {
        // A countdown of months helps nobody, so the header says what the experiment can detect instead.
        const reachable = roundUpDetectableEffect(outlook.reachableEffect)
        const isBeyondMaximum = reachable > MINIMUM_DETECTABLE_EFFECT_MAX
        content = (
            <Tooltip
                title={`Detecting a change of ${targetEffect.toLocaleString()}% needs about ${days.toLocaleString()} more days at the current traffic. Within 4 weeks, the experiment can detect ${
                    isBeyondMaximum
                        ? `only changes over ${MINIMUM_DETECTABLE_EFFECT_MAX}%`
                        : `changes of ${reachable.toLocaleString()}% or more`
                }. The running time settings show what it can detect at each date.`}
            >
                <span className="flex items-center gap-1.5">
                    <IconWarning className="text-warning text-base shrink-0" />
                    <span>
                        {isBeyondMaximum
                            ? `Can detect only changes over ${MINIMUM_DETECTABLE_EFFECT_MAX}% within 4 weeks`
                            : `Can detect ${reachable.toLocaleString()}%+ changes within 4 weeks`}
                    </span>
                </span>
            </Tooltip>
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
