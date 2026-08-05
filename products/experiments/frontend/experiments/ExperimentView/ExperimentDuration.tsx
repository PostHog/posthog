import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'

import { experimentLogic } from '../experimentLogic'

interface DateButtonProps {
    date: string | null | undefined
    type: 'start' | 'end'
    onChange: (date: string) => void
}

const DateButton = ({ date, type, onChange }: DateButtonProps): JSX.Element => {
    const containerWidth = 'w-44'
    const [isOpen, setIsOpen] = useState(false)

    return (
        <div className={containerWidth}>
            <Popover
                actionable
                onClickOutside={() => setIsOpen(false)}
                visible={isOpen}
                overlay={
                    <LemonCalendarSelect
                        value={date ? dayjs(date) : null}
                        onChange={(value) => {
                            onChange(value.toISOString())
                            setIsOpen(false)
                        }}
                        onClose={() => setIsOpen(false)}
                        granularity="minute"
                        selectionPeriod={type === 'start' ? 'past' : undefined}
                    />
                }
            >
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setIsOpen(true)}
                    fullWidth
                    disabledReason={
                        !date && type === 'start'
                            ? 'No start date'
                            : !date && type === 'end'
                              ? 'Experiment is still running'
                              : undefined
                    }
                >
                    {date ? (
                        <TZLabel
                            time={date}
                            formatDate="MMM DD, YYYY"
                            formatTime="hh:mm A"
                            showPopover={true}
                            noStyles={true}
                        />
                    ) : type === 'end' ? (
                        'Present'
                    ) : (
                        'No date'
                    )}
                </LemonButton>
            </Popover>
        </div>
    )
}

export const ExperimentDuration = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)

    const { start_date, end_date } = experiment

    return (
        <div>
            <Label intent="menu">Duration</Label>
            <div className="flex gap-2 items-center">
                <div className="flex items-center gap-2">
                    <DateButton date={start_date} type="start" onChange={changeExperimentStartDate} />
                    <IconArrowRight className="text-base" />
                    <DateButton date={end_date} type="end" onChange={changeExperimentEndDate} />
                </div>
            </div>
        </div>
    )
}
