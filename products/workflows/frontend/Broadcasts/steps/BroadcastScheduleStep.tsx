import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCalendarSelectInput, LemonSearchableSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { pluralize } from 'lib/utils/strings'
import { timeZoneLabel } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SendDayPicker } from '../../SendCalendar/SendDayPicker'
import { describeRule, sendingRule } from '../../SendCalendar/sendSpacing'
import { EmailSendingRateLimitPicker } from '../../Workflows/hogflows/steps/components/EmailSendingRateLimitPicker'
import { RecurringSchedulePicker } from '../../Workflows/hogflows/steps/components/RecurringSchedulePicker'
import { broadcastWizardLogic } from '../broadcastWizardLogic'

function SendingRateLimit(): JSX.Element | null {
    const { emailRateLimit, channel } = useValues(broadcastWizardLogic)
    const { setEmailRateLimit } = useActions(broadcastWizardLogic)

    if (channel !== 'email') {
        return null
    }
    return (
        <div className="max-w-160">
            <EmailSendingRateLimitPicker value={emailRateLimit} onChange={setEmailRateLimit} />
        </div>
    )
}

function SkipFrequencyCap(): JSX.Element | null {
    const { emailSettings, channel } = useValues(broadcastWizardLogic)
    const { setEmailSettings } = useActions(broadcastWizardLogic)
    const { currentTeam } = useValues(teamLogic)
    const config = currentTeam?.workflows_config

    // Transactional email is never capped, and without a cap there is nothing to skip.
    if (
        channel !== 'email' ||
        emailSettings.messageCategoryType === 'transactional' ||
        !config?.marketing_frequency_cap_max_messages ||
        !config?.marketing_frequency_cap_window_days
    ) {
        return null
    }
    const holdHours = config.marketing_frequency_cap_hold_hours
    return (
        <div className="flex flex-col gap-1 max-w-160">
            <LemonSwitch
                label="Send even if people reached your frequency cap"
                checked={emailSettings.skipFrequencyCap}
                onChange={(skipFrequencyCap) => setEmailSettings({ skipFrequencyCap })}
                data-attr="broadcast-skip-frequency-cap"
            />
            <span className="text-secondary text-sm">
                Your{' '}
                <Link to={urls.settings('environment-workflows', 'workflows-frequency-cap')} target="_blank">
                    frequency cap
                </Link>{' '}
                is {describeRule(sendingRule(config))}. People over it{' '}
                {holdHours ? `wait up to ${pluralize(holdHours, 'hour')}, then get skipped` : 'get skipped'}. With this
                on, they get this email when it sends, and it doesn't count toward the cap. Use it for time-sensitive
                email, like an event invite. People who unsubscribed still don't get it.
            </span>
        </div>
    )
}

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
        channel,
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
                <h2 className="m-0 text-xl font-semibold">
                    When should this {channel === 'push' ? 'notification' : 'email'} go out?
                </h2>
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

            {scheduleMode === 'later' ? <SendDayPicker /> : null}

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
                        showRepeatToggle={false}
                        alwaysShowTimezone
                    />
                </div>
            )}

            <SkipFrequencyCap />

            <SendingRateLimit />

            {stepValidationErrors.schedule.map((error) => (
                <div key={error} className="text-danger text-xs">
                    {error}
                </div>
            ))}
        </div>
    )
}
