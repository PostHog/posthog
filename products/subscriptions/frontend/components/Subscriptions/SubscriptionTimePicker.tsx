import { LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

function formatTimeLabel(hour: number, minute: number): string {
    return `${hour % 12 || 12}:${minute.toString().padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`
}

const HALF_HOUR_TIME_OPTIONS: LemonSelectOptionLeaf<string>[] = Array.from({ length: 48 }, (_, index) => {
    const hour = Math.floor(index / 2)
    const minute = (index % 2) * 30

    return {
        value: `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`,
        label: formatTimeLabel(hour, minute),
    }
})

export function SubscriptionTimePicker({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const selectedTime = dayjs(value).format('HH:mm')
    const hasSupportedSelectedTime = HALF_HOUR_TIME_OPTIONS.some((option) => option.value === selectedTime)
    const options: LemonSelectOptionLeaf<string>[] = hasSupportedSelectedTime
        ? HALF_HOUR_TIME_OPTIONS
        : [
              {
                  value: selectedTime,
                  label: `${dayjs(value).format('h:mm A')} (current)`,
                  hidden: true,
              },
              ...HALF_HOUR_TIME_OPTIONS,
          ]

    return (
        <LemonSelect
            aria-label="Delivery time"
            options={options}
            value={selectedTime}
            onChange={(time) => {
                const [hour, minute] = time.split(':').map(Number)
                onChange(dayjs().hour(hour).minute(minute).second(0).toISOString())
            }}
        />
    )
}
