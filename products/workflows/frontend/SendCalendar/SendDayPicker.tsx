import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { broadcastWizardLogic } from '../Broadcasts/broadcastWizardLogic'
import { SendCalendarSendLabel } from './SendCalendarSendLabel'
import { SendDayPickerLegend } from './SendDayPickerLegend'
import { sendDayPickerLogic } from './sendDayPickerLogic'
import { SendDayPickerStatus } from './SendDayPickerStatus'
import { describeRule } from './sendSpacing'

const MAX_SENDS_PER_DAY = 2
const MAX_DOTS_PER_DAY = 6

const HedgehogMailbox = pngHoggie(mailboxPng)

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
        sendAt,
    } = useValues(logic)
    const { pickDay, goForward, goBackward } = useActions(logic)
    const month = anchorDate.slice(0, 7)
    const suggestedDay = suggestion?.tz(effectiveTimezone).format('YYYY-MM-DD') ?? null

    return (
        <div className="@container flex max-w-240 flex-col gap-2" data-attr="send-day-picker">
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
                        const suggested = !isPast && day === suggestedDay && day !== selectedDay
                        return (
                            <Tooltip
                                key={day}
                                title={
                                    crowded
                                        ? `A send at this time gives some people more than ${describeRule(rule)}.`
                                        : undefined
                                }
                            >
                                <button
                                    type="button"
                                    disabled={isPast}
                                    aria-pressed={day === selectedDay}
                                    onClick={() => pickDay(day)}
                                    className={clsx(
                                        'relative flex min-h-16 min-w-0 flex-col gap-0.5 p-1 text-left @min-[44rem]:min-h-20',
                                        index % 7 !== 6 && 'border-r',
                                        index < days.length - 7 && 'border-b',
                                        !day.startsWith(month) && !crowded && 'bg-surface-secondary',
                                        crowded && 'bg-warning-highlight',
                                        isPast && 'cursor-not-allowed opacity-50',
                                        !isPast && day !== selectedDay && 'cursor-pointer hover:bg-fill-highlight-100',
                                        suggested && 'outline-2 -outline-offset-4 outline-dashed outline-success',
                                        day === selectedDay && 'bg-primary-highlight ring-2 ring-inset ring-accent'
                                    )}
                                    data-attr="send-day-picker-day"
                                >
                                    <span className="flex items-center justify-between gap-1 px-1 text-xs font-semibold">
                                        <span
                                            className={clsx(
                                                day === today &&
                                                    'rounded-full bg-accent px-1.5 py-0.5 text-primary-inverse'
                                            )}
                                        >
                                            {dayjs.utc(day).format(dayjs.utc(day).date() === 1 ? 'MMM D' : 'D')}
                                        </span>
                                        {suggested ? (
                                            <LemonTag
                                                type="success"
                                                size="small"
                                                className="hidden @min-[44rem]:inline-flex"
                                            >
                                                Suggested
                                            </LemonTag>
                                        ) : null}
                                    </span>
                                    {day === selectedDay && sendAt ? (
                                        <span className="px-1 text-xs font-semibold text-accent">
                                            {dayjs(sendAt).tz(effectiveTimezone).format('h:mm A')}
                                        </span>
                                    ) : null}
                                    {/* Names need room. A narrow picker shows one dot for each send. */}
                                    <span className="flex flex-wrap gap-0.5 px-1 @min-[44rem]:hidden">
                                        {sends.slice(0, MAX_DOTS_PER_DAY).map((send) => (
                                            <span
                                                key={send.key}
                                                className={clsx(
                                                    'size-2 rounded-full',
                                                    send.kind === 'broadcast'
                                                        ? 'bg-accent'
                                                        : 'bg-[var(--color-product-workflows-light)]',
                                                    !countingKeys[send.key] && 'opacity-40'
                                                )}
                                            />
                                        ))}
                                        {sends.length > MAX_DOTS_PER_DAY ? (
                                            <span className="text-xs leading-2 text-secondary">
                                                +{sends.length - MAX_DOTS_PER_DAY}
                                            </span>
                                        ) : null}
                                    </span>
                                    <span className="hidden min-w-0 flex-col gap-0.5 @min-[44rem]:flex">
                                        {sends.slice(0, MAX_SENDS_PER_DAY).map((send) => (
                                            <span
                                                key={send.key}
                                                className={clsx(
                                                    'min-w-0 overflow-hidden px-1 text-xs',
                                                    !countingKeys[send.key] && 'opacity-40'
                                                )}
                                            >
                                                <SendCalendarSendLabel send={send} timezone={effectiveTimezone} />
                                            </span>
                                        ))}
                                        {sends.length > MAX_SENDS_PER_DAY ? (
                                            <span className="px-1 text-xs text-secondary">
                                                +{sends.length - MAX_SENDS_PER_DAY} more
                                            </span>
                                        ) : null}
                                    </span>
                                    {suggested ? (
                                        <HedgehogMailbox
                                            size="2.25rem"
                                            loading="eager"
                                            className="pointer-events-none absolute right-1.5 bottom-1.5"
                                        />
                                    ) : null}
                                </button>
                            </Tooltip>
                        )
                    })}
                </div>
            </div>
            <SendDayPickerLegend />
            <div className="text-xs text-secondary">
                {rule.fromCap
                    ? `The rule comes from your frequency cap: ${describeRule(rule)}.`
                    : `No frequency cap is set, so the rule is ${describeRule(rule)}.`}
            </div>
        </div>
    )
}
