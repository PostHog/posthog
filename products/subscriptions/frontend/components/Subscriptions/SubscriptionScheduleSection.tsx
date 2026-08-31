import { useValues } from 'kea'

import { NextScheduledRun, ProjectTimezoneNotice } from 'lib/components/ScheduledRunStatus'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SubscriptionDayPicker } from './SubscriptionDayPicker'
import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionLogicProps } from './subscriptionLogic'
import {
    bysetposOptions,
    frequencyOptionsPlural,
    frequencyOptionsSingular,
    getNextDeliveryDate,
    intervalOptions,
    monthlyWeekdayOptions,
    shouldShowDayPicker,
    timeOptions,
    WEEKDAYS,
    weekdayOptions,
} from './utils'

export function SubscriptionScheduleSection({ logicProps }: { logicProps: SubscriptionLogicProps }): JSX.Element {
    const { subscription } = useValues(subscriptionLogic(logicProps))
    const { currentTeam } = useValues(teamLogic)
    const availableFrequencyOptions = subscription?.interval === 1 ? frequencyOptionsSingular : frequencyOptionsPlural
    const nextDeliveryDate = subscription ? getNextDeliveryDate(subscription) : null

    return (
        <div className="flex min-w-0 flex-col gap-4">
            <LemonLabel>When should we send it?</LemonLabel>
            <div className="flex flex-wrap items-center gap-2 rounded border p-3">
                <span>Every</span>
                <LemonField name="interval">
                    <LemonSelect options={intervalOptions} />
                </LemonField>
                <LemonField name="frequency" renderError={() => null}>
                    <LemonSelect options={availableFrequencyOptions} />
                </LemonField>
                {subscription && shouldShowDayPicker(subscription.frequency, subscription.interval) ? (
                    <>
                        <span>on</span>
                        <LemonField name="byweekday">
                            {({ value, onChange }) => <SubscriptionDayPicker value={value ?? []} onChange={onChange} />}
                        </LemonField>
                    </>
                ) : null}
                {subscription?.frequency === 'monthly' ? (
                    <>
                        <span>on the</span>
                        <LemonField name="bysetpos">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    options={bysetposOptions}
                                    value={value ? String(value) : null}
                                    onChange={(nextValue) => onChange(nextValue === null ? null : Number(nextValue))}
                                />
                            )}
                        </LemonField>
                        <LemonField name="byweekday">
                            {({ value, onChange }) => {
                                const isWeekday = value?.length === 5 && value.every((day: string) => WEEKDAYS.has(day))
                                let displayValue = 'day'
                                if (isWeekday) {
                                    displayValue = 'weekday'
                                } else if (value?.length === 1) {
                                    displayValue = value[0]
                                }
                                return (
                                    <LemonSelect
                                        dropdownMatchSelectWidth={false}
                                        options={monthlyWeekdayOptions}
                                        value={displayValue}
                                        onChange={(nextValue) => {
                                            if (nextValue === 'day') {
                                                onChange(weekdayOptions.map(({ value }) => value))
                                                return
                                            }
                                            if (nextValue === 'weekday') {
                                                onChange([...WEEKDAYS])
                                                return
                                            }
                                            onChange([nextValue])
                                        }}
                                    />
                                )
                            }}
                        </LemonField>
                    </>
                ) : null}
                <span>at</span>
                <LemonField name="start_date">
                    {({ value, onChange }) => (
                        <LemonSelect
                            options={timeOptions}
                            value={dayjs(value).hour().toString()}
                            onChange={(hour) =>
                                onChange(
                                    dayjs()
                                        .hour(Number(hour ?? 0))
                                        .minute(0)
                                        .second(0)
                                        .toISOString()
                                )
                            }
                        />
                    )}
                </LemonField>
            </div>
            {nextDeliveryDate ? (
                <div className="flex flex-col gap-3">
                    <NextScheduledRun label="Next planned delivery:">
                        <span>
                            Approximately <TZLabel time={dayjs(nextDeliveryDate)} />
                        </span>
                    </NextScheduledRun>
                    <ProjectTimezoneNotice
                        timezone={currentTeam?.timezone ?? 'UTC'}
                        settingsUrl={urls.settings('environment-customization', 'date-and-time')}
                    />
                </div>
            ) : null}
        </div>
    )
}
