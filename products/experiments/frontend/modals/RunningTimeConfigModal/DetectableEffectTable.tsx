import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Label } from 'lib/ui/Label/Label'
import {
    DetectableEffectCheckpoint,
    MINIMUM_DETECTABLE_EFFECT_MAX,
    MINIMUM_DETECTABLE_EFFECT_MIN,
    formatDetectableEffect,
    roundUpDetectableEffect,
} from 'scenes/experiments/RunningTimeCalculator/calculations'
import { runningTimeLogic } from 'scenes/experiments/RunningTimeCalculator/runningTimeLogic'

import { Experiment } from '~/types'

export interface DetectableEffectTableProps {
    experiment: Experiment
}

function formatDate(date: dayjs.Dayjs): string {
    return date.format(date.isSame(dayjs(), 'year') ? 'MMM D' : 'MMM D, YYYY')
}

function setTargetDisabledReason(effect: number): string | undefined {
    if (effect > MINIMUM_DETECTABLE_EFFECT_MAX) {
        return `The minimum detectable effect can be at most ${MINIMUM_DETECTABLE_EFFECT_MAX}%`
    }
    if (effect < MINIMUM_DETECTABLE_EFFECT_MIN) {
        return `The minimum detectable effect must be at least ${MINIMUM_DETECTABLE_EFFECT_MIN}%`
    }
    return undefined
}

export function DetectableEffectTable({ experiment: experimentProp }: DetectableEffectTableProps): JSX.Element | null {
    const logic = runningTimeLogic({ experiment: experimentProp })
    const {
        outlook,
        remainingDays,
        isComplete,
        dailyExposureRate,
        currentExposures,
        targetSampleSize,
        targetEffect,
        canIncludeMoreUsers,
        experiment,
    } = useValues(logic)
    const { setConfig } = useActions(logic)

    if (!outlook || remainingDays === null || dailyExposureRate === null || !experiment.start_date) {
        return null
    }

    const exposuresTooltip =
        targetSampleSize !== null && currentExposures !== null
            ? `Needs ${targetSampleSize.toLocaleString()} exposures. ${currentExposures.toLocaleString()} so far.`
            : undefined
    const dateAt = (days: number): dayjs.Dayjs => dayjs(experiment.start_date).add(days * 24, 'hour')
    const daysLeft = Math.ceil(remainingDays)

    const since = ({ kind, days }: DetectableEffectCheckpoint): string => {
        if (kind === 'week') {
            return `week ${days / 7}`
        }
        if (kind === 'target' && !isComplete) {
            return `in ${daysLeft.toLocaleString()} ${daysLeft === 1 ? 'day' : 'days'}`
        }
        // The day in progress, so that the first day of an experiment is day 1.
        return `day ${Math.max(1, Math.ceil(days)).toLocaleString()}`
    }

    return (
        <div className="space-y-2" data-attr="experiment-running-time-outlook">
            <Label intent="menu">What the experiment can detect</Label>
            <LemonTable
                size="small"
                embedded
                dataSource={outlook.checkpoints}
                rowKey={(checkpoint) => checkpoint.kind + checkpoint.days}
                rowStatus={(checkpoint) => (checkpoint.kind === 'target' ? 'highlighted' : null)}
                rowClassName={(checkpoint) => (checkpoint.kind === 'target' ? 'font-semibold' : null)}
                columns={[
                    {
                        title: 'When',
                        key: 'when',
                        render: (_, checkpoint) => (
                            <span className="flex items-center gap-1.5 whitespace-nowrap">
                                {checkpoint.kind === 'target' && isComplete && (
                                    <Tooltip title="Target reached">
                                        <IconCheck className="text-success shrink-0" />
                                    </Tooltip>
                                )}
                                {checkpoint.kind === 'target' && outlook.isOutOfReach && (
                                    <Tooltip title="More than 4 weeks from today. Most experiments end within 4 weeks.">
                                        <IconWarning className="text-warning shrink-0" />
                                    </Tooltip>
                                )}
                                <span>{checkpoint.kind === 'now' ? 'Today' : formatDate(dateAt(checkpoint.days))}</span>
                                <span className="text-muted font-normal">{`· ${since(checkpoint)}`}</span>
                            </span>
                        ),
                    },
                    {
                        title: 'Detectable effect',
                        key: 'detectable',
                        align: 'right',
                        render: (_, checkpoint) => <span>{formatDetectableEffect(checkpoint.detectableEffect)}</span>,
                    },
                    {
                        key: 'set-target',
                        align: 'right',
                        width: 0,
                        render: (_, checkpoint) => {
                            if (checkpoint.kind === 'target') {
                                return (
                                    <Tooltip title={exposuresTooltip}>
                                        <LemonTag type="highlight" size="small">
                                            Target
                                        </LemonTag>
                                    </Tooltip>
                                )
                            }
                            const effect = roundUpDetectableEffect(checkpoint.detectableEffect)
                            if (effect === targetEffect) {
                                return null
                            }
                            return (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    disabledReason={setTargetDisabledReason(effect)}
                                    tooltip={`Set ${effect.toLocaleString()}% as the minimum detectable effect`}
                                    onClick={() => setConfig({ mde: effect })}
                                    data-attr="experiment-running-time-set-target"
                                >
                                    Use
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
            <div className="text-xs text-secondary">
                {`Dates assume about ${Math.round(dailyExposureRate).toLocaleString()} exposures a day, the average since launch.${
                    outlook.isOutOfReach && canIncludeMoreUsers
                        ? ' To finish sooner, include more users in the experiment.'
                        : ''
                }`}
            </div>
        </div>
    )
}
