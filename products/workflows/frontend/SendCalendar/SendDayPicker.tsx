import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { broadcastWizardLogic } from '../Broadcasts/broadcastWizardLogic'
import { SendCalendarSendLabel } from './SendCalendarSendLabel'
import { sendDayPickerLogic } from './sendDayPickerLogic'
import { SendDayPickerStatus } from './SendDayPickerStatus'
import { describeRule } from './sendSpacing'

const MAX_SENDS_PER_DAY = 2

export function SendDayPicker(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = sendDayPickerLogic(props)
    const {
        days,
        anchorDate,
        today,
        sendsByDay,
        countingKeys,
        crowdedDays,
        selectedDay,
        suggestion,
        rule,
        isTransactional,
        effectiveTimezone,
    } = useValues(logic)
    const { pickDay, goForward, goBackward } = useActions(logic)
    const month = anchorDate.slice(0, 7)
    const suggestedDay = suggestion?.tz(effectiveTimezone).format('YYYY-MM-DD') ?? null

    return (
        <div className="flex max-w-240 flex-col gap-2" data-attr="send-day-picker">
            <SendDayPickerStatus />
            <div className="overflow-hidden rounded border bg-surface-primary">
                <div className="flex items-center gap-1 border-b px-2 py-1">
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronLeft />}
                        onClick={goBackward}
                        tooltip="Previous month"
                        data-attr="send-day-picker-previous"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronRight />}
                        onClick={goForward}
                        tooltip="Next month"
                        data-attr="send-day-picker-next"
                    />
                    <span className="ml-1 text-sm font-semibold">{dayjs.utc(anchorDate).format('MMMM YYYY')}</span>
                </div>
                <div className="grid grid-cols-7 border-b bg-surface-secondary">
                    {days.slice(0, 7).map((day) => (
                        <div key={day} className="px-2 py-1 text-xs font-semibold uppercase text-secondary">
                            {dayjs.utc(day).format('ddd')}
                        </div>
                    ))}
                </div>
                <div className="grid grid-cols-7">
                    {days.map((day, index) => {
                        const sends = sendsByDay[day] ?? []
                        const isPast = day < today
                        const crowded = !isTransactional && !isPast && crowdedDays[day]
                        return (
                            <button
                                key={day}
                                type="button"
                                disabled={isPast}
                                aria-pressed={day === selectedDay}
                                onClick={() => pickDay(day)}
                                className={clsx(
                                    'flex min-h-20 min-w-0 flex-col gap-0.5 p-1 text-left',
                                    index % 7 !== 6 && 'border-r',
                                    index < days.length - 7 && 'border-b',
                                    !day.startsWith(month) && 'bg-surface-secondary',
                                    isPast
                                        ? 'cursor-not-allowed opacity-50'
                                        : 'cursor-pointer hover:bg-fill-highlight-100',
                                    day === selectedDay && 'bg-primary-highlight ring-2 ring-inset ring-accent'
                                )}
                                data-attr="send-day-picker-day"
                            >
                                <span className="flex items-center justify-between gap-1 px-1 text-xs font-semibold">
                                    <span className={clsx(day === today && 'text-accent')}>
                                        {dayjs.utc(day).format(dayjs.utc(day).date() === 1 ? 'MMM D' : 'D')}
                                    </span>
                                    {crowded ? (
                                        <Tooltip
                                            title={`A send at this time gives some people more than ${describeRule(rule)}.`}
                                        >
                                            <IconWarning
                                                className="text-warning"
                                                aria-label="Too close to other sends"
                                            />
                                        </Tooltip>
                                    ) : day === suggestedDay ? (
                                        <span className="font-normal text-success">Suggested</span>
                                    ) : null}
                                </span>
                                {sends.slice(0, MAX_SENDS_PER_DAY).map((send) => (
                                    <span
                                        key={send.key}
                                        className={clsx('px-1 text-xs', !countingKeys[send.key] && 'opacity-50')}
                                    >
                                        <SendCalendarSendLabel send={send} timezone={effectiveTimezone} />
                                    </span>
                                ))}
                                {sends.length > MAX_SENDS_PER_DAY ? (
                                    <span className="px-1 text-xs text-secondary">
                                        +{sends.length - MAX_SENDS_PER_DAY} more
                                    </span>
                                ) : null}
                            </button>
                        )
                    })}
                </div>
            </div>
            <div className="text-xs text-secondary">
                {rule.fromCap
                    ? `Suggestions follow your frequency cap: ${describeRule(rule)}.`
                    : `No frequency cap is set, so suggestions keep to ${describeRule(rule)}.`}{' '}
                Faded sends don't count, because they are transactional or go to other cohorts.
            </div>
        </div>
    )
}
