import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Label } from 'lib/ui/Label/Label'
import {
    describeCheckpointDay,
    describeUseButton,
    formatDetectableEffect,
} from 'scenes/experiments/RunningTimeCalculator/calculations'
import { runningTimeLogic } from 'scenes/experiments/RunningTimeCalculator/runningTimeLogic'

import { Experiment } from '~/types'

export interface DetectableEffectTableProps {
    experiment: Experiment
}

function formatDate(date: dayjs.Dayjs): string {
    return date.format(date.isSame(dayjs(), 'year') ? 'MMM D' : 'MMM D, YYYY')
}

export function DetectableEffectTable({ experiment: experimentProp }: DetectableEffectTableProps): JSX.Element | null {
    const logic = runningTimeLogic({ experiment: experimentProp })
    const {
        outlook,
        currentExposures,
        isComplete,
        dailyExposureRate,
        estimateMetric,
        canIncludeMoreUsers,
        experiment,
    } = useValues(logic)
    const { selectCheckpoint } = useActions(logic)

    const startDate = experiment.start_date
    if (!outlook || currentExposures === null || dailyExposureRate === null || !startDate) {
        return null
    }

    const dateAt = (days: number): dayjs.Dayjs => dayjs(startDate).add(days * 24, 'hour')

    return (
        <div className="space-y-2" data-attr="experiment-running-time-outlook">
            <Label intent="menu">What the experiment can detect</Label>
            <LemonTable
                size="small"
                embedded
                dataSource={outlook.checkpoints}
                rowKey={(checkpoint) => checkpoint.key}
                rowStatus={(checkpoint) => (checkpoint.isTarget ? 'highlighted' : null)}
                rowClassName={(checkpoint) => (checkpoint.isTarget ? 'font-semibold' : null)}
                columns={[
                    {
                        title: 'When',
                        key: 'when',
                        // Takes the spare width, so that the number columns stay in place while the target row moves.
                        width: '100%',
                        render: (_, checkpoint) => (
                            <span className="flex items-center gap-1.5 whitespace-nowrap">
                                {checkpoint.isTarget && isComplete && (
                                    <Tooltip title="Target reached">
                                        <IconCheck className="text-success shrink-0" />
                                    </Tooltip>
                                )}
                                {checkpoint.isTarget && outlook.isOutOfReach && (
                                    <Tooltip title="More than 4 weeks from today. Most experiments end within 4 weeks.">
                                        <IconWarning className="text-warning shrink-0" />
                                    </Tooltip>
                                )}
                                <span>{checkpoint.kind === 'now' ? 'Today' : formatDate(dateAt(checkpoint.days))}</span>
                                <span className="text-muted font-normal">{`· ${describeCheckpointDay(checkpoint, {
                                    startDate,
                                    currentSampleSize: currentExposures,
                                })}`}</span>
                            </span>
                        ),
                    },
                    {
                        title: 'Exposures',
                        key: 'exposures',
                        align: 'right',
                        render: (_, checkpoint) => <span>{checkpoint.exposures.toLocaleString()}</span>,
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
                            if (checkpoint.isTarget) {
                                return (
                                    <LemonTag type="highlight" size="small">
                                        Target
                                    </LemonTag>
                                )
                            }
                            const { effect, disabledReason, tooltip } = describeUseButton(checkpoint)
                            return (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    disabledReason={disabledReason}
                                    tooltip={tooltip}
                                    onClick={() => selectCheckpoint(checkpoint.key, effect)}
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
                <span>Based on </span>
                <span className="font-semibold">{estimateMetric?.name ?? 'the primary metric'}</span>
                <span>
                    {`${estimateMetric ? `, the ${estimateMetric.isFirstOfSeveral ? 'first ' : ''}primary metric` : ''}.${
                        estimateMetric?.hasOtherMetrics ? ' Other metrics can need more time.' : ''
                    } Projections assume about ${Math.round(dailyExposureRate).toLocaleString()} exposures a day, the average since launch.${
                        outlook.isOutOfReach && canIncludeMoreUsers
                            ? ' To finish sooner, include more users in the experiment.'
                            : ''
                    }`}
                </span>
            </div>
        </div>
    )
}
