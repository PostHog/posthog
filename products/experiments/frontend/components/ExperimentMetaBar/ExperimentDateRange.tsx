import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCalendar } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

interface DateTriggerProps {
    date: string | null | undefined
    boundary: 'start' | 'end'
    onApply: (date: string) => void
}

function DateTrigger({ date, boundary, onApply }: DateTriggerProps): JSX.Element {
    const { openDatePicker, experimentUpdateLoading } = useValues(experimentLogic)
    const { setOpenDatePicker } = useActions(experimentLogic)
    const isOpen = openDatePicker === boundary

    // A successful save closes the picker. If the picker could close while the save runs, that save would close a
    // picker that the user opened again.
    const close = (): void => {
        if (!experimentUpdateLoading) {
            setOpenDatePicker(null)
        }
    }

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
            onClickOutside={close}
            overlay={
                <LemonCalendarSelect
                    value={date ? dayjs(date) : null}
                    onChange={(value) => onApply(value.toISOString())}
                    onClose={close}
                    loading={experimentUpdateLoading}
                    granularity="minute"
                    selectionPeriod={boundary === 'start' ? 'past' : undefined}
                />
            }
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                sideIcon={null}
                onClick={() => setOpenDatePicker(boundary)}
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
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)

    return (
        <div className="flex items-center gap-0.5" data-attr="experiment-date-range">
            <Tooltip title="Duration">
                <IconCalendar className="text-secondary text-base shrink-0 mr-1" />
            </Tooltip>
            <DateTrigger date={experiment.start_date} boundary="start" onApply={changeExperimentStartDate} />
            <IconArrowRight className="text-tertiary shrink-0" />
            <DateTrigger date={experiment.end_date} boundary="end" onApply={changeExperimentEndDate} />
        </div>
    )
}
