import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight, IconCalendar } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

interface DateTriggerProps {
    date: string | null | undefined
    boundary: 'start' | 'end'
    onChange: (date: string) => void
}

function DateTrigger({ date, boundary, onChange }: DateTriggerProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    const label = date ? dayjs(date).format('MMM D, YYYY') : boundary === 'end' ? 'Present' : 'No date'
    const tooltip = date
        ? `${boundary === 'start' ? 'Started' : 'Ended'} ${dayjs(date).format('MMM D, YYYY [at] h:mm A')}. Click to change.`
        : undefined
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
                    onChange={(value) => {
                        onChange(value.toISOString())
                        setIsOpen(false)
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
                tooltip={tooltip}
                disabledReason={disabledReason}
                data-attr={`experiment-${boundary}-date`}
            >
                {label}
            </LemonButton>
        </Popover>
    )
}

export function ExperimentDateRange(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)

    return (
        <div className="flex items-center gap-0.5" data-attr="experiment-date-range">
            <Tooltip title="Duration">
                <IconCalendar className="text-secondary text-base shrink-0 mr-1" />
            </Tooltip>
            <DateTrigger date={experiment.start_date} boundary="start" onChange={changeExperimentStartDate} />
            <IconArrowRight className="text-tertiary shrink-0" />
            <DateTrigger date={experiment.end_date} boundary="end" onChange={changeExperimentEndDate} />
        </div>
    )
}
