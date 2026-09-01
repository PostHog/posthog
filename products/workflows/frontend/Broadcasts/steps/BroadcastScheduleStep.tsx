import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCalendarSelectInput, LemonSearchableSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { timeZoneLabel } from 'lib/utils/timezones'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { RecurringSchedulePicker } from '../../Workflows/hogflows/steps/components/RecurringSchedulePicker'
import { broadcastWizardLogic } from '../broadcastWizardLogic'

function TimezonePicker({ value, onChange }: { value: string; onChange: (timezone: string) => void }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const options = useMemo(
        () =>
            Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
                value: tz,
                label: timeZoneLabel(tz, offset),
            })),
        [preflight?.available_timezones]
    )

    return (
        <LemonSearchableSelect
            value={value}
            options={options}
            onChange={(val) => val && onChange(val)}
            searchPlaceholder="Search timezones..."
            fullWidth
        />
    )
}

export function BroadcastScheduleStep(): JSX.Element {
    const {
        scheduleMode,
        sendAt,
        scheduleState,
        recurringStartsAt,
        recurringRepeating,
        effectiveTimezone,
        stepValidationErrors,
    } = useValues(broadcastWizardLogic)
    const {
        setScheduleMode,
        setSendAtFromPicker,
        setScheduleState,
        setRecurringStartsAtFromPicker,
        setRecurringRepeating,
        setScheduleTimezone,
    } = useActions(broadcastWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="m-0 text-xl font-semibold">When should this email go out?</h2>
                <p className="m-0 text-secondary">Send it right away, pick a time, or set up a repeating schedule.</p>
            </div>

            <LemonRadio
                value={scheduleMode}
                onChange={setScheduleMode}
                options={[
                    { value: 'now', label: 'Send now' },
                    { value: 'later', label: 'Send later' },
                    { value: 'recurring', label: 'Recurring' },
                ]}
            />

            {scheduleMode === 'later' && (
                <div className="flex flex-col gap-2 max-w-160">
                    <LemonCalendarSelectInput
                        buttonProps={{ fullWidth: true }}
                        format="MMMM D, YYYY h:mm A"
                        clearable
                        value={sendAt ? dayjs(sendAt).tz(effectiveTimezone).tz(dayjs.tz.guess(), true) : null}
                        onChange={(date) => setSendAtFromPicker(date ? date.toISOString() : null)}
                        granularity="minute"
                        selectionPeriod="upcoming"
                        showTimeToggle={false}
                    />
                    <TimezonePicker
                        value={effectiveTimezone}
                        onChange={(timezone) => setScheduleTimezone(timezone, effectiveTimezone)}
                    />
                    {effectiveTimezone !== dayjs.tz.guess() && sendAt && (
                        <span className="text-xs text-muted">
                            Sends at {dayjs(sendAt).tz(effectiveTimezone).format('h:mm A')} {effectiveTimezone} · Your
                            time: {dayjs(sendAt).format('h:mm A')} {dayjs.tz.guess()}
                        </span>
                    )}
                </div>
            )}

            {scheduleMode === 'recurring' && (
                <div className="max-w-160">
                    <RecurringSchedulePicker
                        state={scheduleState}
                        startsAt={recurringStartsAt}
                        timezone={effectiveTimezone}
                        repeating={recurringRepeating}
                        onStateChange={setScheduleState}
                        onStartsAtChange={setRecurringStartsAtFromPicker}
                        onTimezoneChange={setScheduleTimezone}
                        onRepeatingChange={setRecurringRepeating}
                    />
                </div>
            )}

            {stepValidationErrors.schedule.map((error) => (
                <div key={error} className="text-danger text-xs">
                    {error}
                </div>
            ))}
        </div>
    )
}
