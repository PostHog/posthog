import { useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight, IconCalendar } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { type ExperimentSaveOutcome, dispatchExperimentSave, experimentLogic } from 'scenes/experiments/experimentLogic'

interface DateTriggerProps {
    date: string | null | undefined
    boundary: 'start' | 'end'
    onChange: (date: string) => Promise<ExperimentSaveOutcome>
}

function DateTrigger({ date, boundary, onChange }: DateTriggerProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    const label = date ? dayjs(date).format('MMM D, YYYY') : boundary === 'end' ? 'Present' : 'No date'
    const disabledReason = !date
        ? boundary === 'start'
            ? 'No start date'
            : 'The experiment is still running'
        : undefined

    return (
        <Popover
            actionable
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <LemonCalendarSelect
                    value={date ? dayjs(date) : null}
                    onChange={async (value) => {
                        // The save reports its own error, so a failed save only keeps the picker open for a retry.
                        if ((await onChange(value.toISOString())) === 'saved') {
                            setIsOpen(false)
                        }
                    }}
                    onClose={() => setIsOpen(false)}
                    granularity="minute"
                    selectionPeriod={boundary === 'start' ? 'past' : undefined}
                />
            }
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                sideIcon={null}
                onClick={() => setIsOpen(true)}
                disabledReason={disabledReason}
                data-attr={`experiment-${boundary}-date`}
            >
                {date ? (
                    // Hidden while the calendar is open so the two popovers do not stack.
                    <TZLabel
                        time={date}
                        title={boundary === 'start' ? 'Start date' : 'End date'}
                        visible={isOpen ? false : undefined}
                    >
                        <span>{label}</span>
                    </TZLabel>
                ) : (
                    label
                )}
            </LemonButton>
        </Popover>
    )
}

export function ExperimentDateRange(): JSX.Element {
    const { experiment, experimentId } = useValues(experimentLogic)

    return (
        <div className="flex items-center gap-0.5" data-attr="experiment-date-range">
            <Tooltip title="Duration">
                <IconCalendar className="text-secondary text-base shrink-0 mr-1" />
            </Tooltip>
            <DateTrigger
                date={experiment.start_date}
                boundary="start"
                onChange={(date) =>
                    dispatchExperimentSave(experimentId, (actions) => actions.changeExperimentStartDate(date))
                }
            />
            <IconArrowRight className="text-tertiary shrink-0" />
            <DateTrigger
                date={experiment.end_date}
                boundary="end"
                onChange={(date) =>
                    dispatchExperimentSave(experimentId, (actions) => actions.changeExperimentEndDate(date))
                }
            />
        </div>
    )
}
