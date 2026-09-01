import { LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { WeekdayType } from '~/types'

import { ALL_DAYS, selectedDaysToDayPickerLabel, toggleSelectedDay, weekdayOptions } from './utils'

interface SubscriptionDayPickerProps {
    value: WeekdayType[]
    onChange: (value: WeekdayType[]) => void
}

export function SubscriptionDayPicker({ value, onChange }: SubscriptionDayPickerProps): JSX.Element {
    let selectAllChecked: boolean | 'indeterminate' = false
    if (value.length === ALL_DAYS.length) {
        selectAllChecked = true
    } else if (value.length > 0) {
        selectAllChecked = 'indeterminate'
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <div className="w-48 flex flex-col gap-0.5">
                    <div className="flex items-center mb-0.5">
                        <LemonButton
                            size="small"
                            className="flex-1"
                            icon={<LemonCheckbox checked={selectAllChecked} className="pointer-events-none" />}
                            disabledReason={value.length === ALL_DAYS.length ? 'All days are selected' : undefined}
                            onClick={() => onChange([...ALL_DAYS])}
                        >
                            Select all
                        </LemonButton>
                        <LemonButton
                            size="small"
                            disabledReason={value.length === 0 ? 'No days are selected' : undefined}
                            onClick={() => onChange([])}
                        >
                            Clear all
                        </LemonButton>
                    </div>
                    {weekdayOptions.map((day) => (
                        <LemonCheckbox
                            key={day.value}
                            checked={value.includes(day.value)}
                            label={day.label}
                            fullWidth
                            className="px-2 py-1 rounded hover:bg-bg-3000"
                            onChange={() => onChange(toggleSelectedDay(value, day.value))}
                        />
                    ))}
                </div>
            }
        >
            <LemonButton type="secondary">{selectedDaysToDayPickerLabel(value)}</LemonButton>
        </LemonDropdown>
    )
}
