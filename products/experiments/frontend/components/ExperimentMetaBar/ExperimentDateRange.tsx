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

export function useDateTrigger(
    date: string | null | undefined,
    boundary: 'start' | 'end'
): {
    isOpen: boolean
    open: () => void
    close: () => void
    loading: boolean
    label: string
    disabledReason?: string
} {
    const { openDatePicker, experimentUpdateLoading } = useValues(experimentLogic)
    const { setOpenDatePicker } = useActions(experimentLogic)

    return {
        isOpen: openDatePicker === boundary,
        open: () => setOpenDatePicker(boundary),
        // A successful save closes the picker. If the picker could close while the save runs, that save would close a
        // picker that the user opened again.
        close: () => {
            if (!experimentUpdateLoading) {
                setOpenDatePicker(null)
            }
        },
        loading: experimentUpdateLoading,
        label: date ? dayjs(date).format('MMM D, YYYY') : boundary === 'end' ? 'Present' : 'No date',
        disabledReason: !date
            ? boundary === 'start'
                ? 'No start date'
                : 'The experiment is still running'
            : undefined,
    }
}

function DateTrigger({ date, boundary, onApply }: DateTriggerProps): JSX.Element {
    const { isOpen, open, close, loading, label, disabledReason } = useDateTrigger(date, boundary)

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
                    loading={loading}
                    granularity="minute"
                    selectionPeriod={boundary === 'start' ? 'past' : undefined}
                />
            }
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                sideIcon={null}
                onClick={open}
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
                        <span className="font-normal">{label}</span>
                    </TZLabel>
                ) : (
                    <span className="font-normal">{label}</span>
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
