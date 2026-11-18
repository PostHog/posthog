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

export type RemainingTimeState =
    | { kind: 'calculating' }
    | { kind: 'pending'; label: string }
    | { kind: 'complete' }
    | { kind: 'out-of-reach'; label: string; tooltip: string }
    | { kind: 'days'; label: string; progress: number | null }

export function useRemainingTime(experiment: Experiment): {
    state: RemainingTimeState
    launched: boolean
    showProgress: boolean
    iconTooltip: string
    configureTooltip: string
} {
    const { remainingDays, currentExposures, targetSampleSize, isComplete, isCalculating, outlook, targetEffect } =
        useValues(runningTimeLogic({ experiment }))

    const launched = isLaunched(experiment)
    const showProgress = currentExposures !== null && targetSampleSize !== null
    const days = remainingDays === null ? null : Math.ceil(remainingDays)

    let state: RemainingTimeState
    if (isCalculating) {
        state = { kind: 'calculating' }
    } else if (days === null) {
        state = { kind: 'pending', label: launched ? 'Duration pending' : 'No duration estimate' }
    } else if (isComplete) {
        state = { kind: 'complete' }
    } else if (outlook?.isOutOfReach) {
        // A countdown of months helps nobody, so the header says what the experiment can detect instead.
        const reachable = roundUpDetectableEffect(outlook.reachableEffect)
        const isBeyondMaximum = reachable > MINIMUM_DETECTABLE_EFFECT_MAX
        state = {
            kind: 'out-of-reach',
            tooltip: `Detecting a change of ${targetEffect.toLocaleString()}% needs about ${days.toLocaleString()} more days at the current traffic. Within 4 weeks, the experiment can detect ${
                isBeyondMaximum
                    ? `only changes over ${MINIMUM_DETECTABLE_EFFECT_MAX}%`
                    : `changes of ${reachable.toLocaleString()}% or more`
            }. The running time settings show what it can detect at each date.`,
            label: isBeyondMaximum
                ? `Can detect only changes over ${MINIMUM_DETECTABLE_EFFECT_MAX}% within 4 weeks`
                : `Can detect ${reachable.toLocaleString()}%+ changes within 4 weeks`,
        }
    } else {
        state = {
            kind: 'days',
            label: `~${days} ${days === 1 ? 'day' : 'days'} ${launched ? 'left' : 'estimated'}`,
            progress: showProgress ? Math.min(currentExposures / targetSampleSize, 1) : null,
        }
    }

    return {
        state,
        launched,
        showProgress,
        iconTooltip: launched ? 'Remaining time' : 'Estimated duration',
        configureTooltip: launched ? 'Configure target duration' : 'Estimate duration',
    }
}

export function ExperimentRemainingTime({
    experiment,
    onConfigure,
}: {
    experiment: Experiment
    onConfigure: () => void
}): JSX.Element {
    const { state, showProgress, iconTooltip, configureTooltip } = useRemainingTime(experiment)

    let content: JSX.Element
    if (state.kind === 'calculating') {
        content = <span className="text-secondary">Calculating…</span>
    } else if (state.kind === 'pending') {
        content = <span className="text-secondary">{state.label}</span>
    } else if (state.kind === 'complete') {
        content = (
            <span className="flex items-center gap-1">
                <IconCheck className="text-success" />
                <span>Target reached</span>
            </span>
        )
    } else if (state.kind === 'out-of-reach') {
        content = (
            <Tooltip title={state.tooltip}>
                <span className="flex items-center gap-1.5">
                    <IconWarning className="text-warning text-base shrink-0" />
                    <span>{state.label}</span>
                </span>
            </Tooltip>
        )
    } else {
        content = (
            <span className="flex items-center gap-1.5">
                {state.progress !== null && <LemonProgressCircle progress={state.progress} size={16} />}
                <span>{state.label}</span>
            </span>
        )
    }

    return (
        <div className="flex items-center gap-1.5" data-attr="experiment-remaining-time">
            {!showProgress && (
                <Tooltip title={iconTooltip}>
                    <IconHourglass className="text-secondary text-base shrink-0" />
                </Tooltip>
            )}
            {content}
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconGear />}
                onClick={onConfigure}
                tooltip={configureTooltip}
                data-attr="experiment-running-time-config"
            />
        </div>
    )
}
