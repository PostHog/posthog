import type { CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const FREQUENCY_OPTIONS: { value: CheckFrequencyEnumApi; label: string }[] = [
    { value: 'daily', label: 'Daily' },
    { value: 'every_3_days', label: 'Every 72 hours' },
    { value: 'weekly', label: 'Weekly' },
]

export const frequencyLabel = (frequency: CheckFrequencyEnumApi): string =>
    FREQUENCY_OPTIONS.find((option) => option.value === frequency)?.label ?? frequency
