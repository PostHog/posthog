import { LemonSelect } from '@posthog/lemon-ui'

// Mirrors the backend's `_INTERVAL_LADDER`, finest first.
const INTERVAL_STEPS: { value: string; label: string }[] = [
    { value: 'second', label: '1 second' },
    { value: 'minute', label: '1 minute' },
    { value: 'minute_5', label: '5 minutes' },
    { value: 'minute_15', label: '15 minutes' },
    { value: 'hour', label: '1 hour' },
    { value: 'hour_6', label: '6 hours' },
    { value: 'day', label: '1 day' },
    { value: 'week', label: '1 week' },
]

// LemonSelect values cannot be null, so "auto" and "no minimum" share one sentinel.
const NONE = 'none'

const INTERVAL_OPTIONS = [
    { value: NONE, label: 'Auto interval' },
    ...INTERVAL_STEPS.map(({ value, label }) => ({ value, label: `Every ${label}` })),
]

const MIN_INTERVAL_OPTIONS = [
    { value: NONE, label: 'No min interval' },
    ...INTERVAL_STEPS.map(({ value, label }) => ({ value, label: `Min ${label}` })),
]

interface IntervalSelectProps {
    value: string | null
    onChange: (value: string | null) => void
    disabledReason?: string | null
}

/** Bucket size for the chart. The backend coarsens a step that would need too many buckets for the range. */
export function MetricsIntervalPicker({ value, onChange, disabledReason }: IntervalSelectProps): JSX.Element {
    return (
        <LemonSelect
            size="small"
            value={value ?? NONE}
            options={INTERVAL_OPTIONS}
            onChange={(next) => onChange(next === NONE ? null : next)}
            disabledReason={disabledReason}
            data-attr="metrics-interval"
        />
    )
}

/** The finest bucket size the chart may use, for metrics sent less often than the auto pick. */
export function MetricsMinIntervalPicker({ value, onChange, disabledReason }: IntervalSelectProps): JSX.Element {
    return (
        <LemonSelect
            size="small"
            value={value ?? NONE}
            options={MIN_INTERVAL_OPTIONS}
            onChange={(next) => onChange(next === NONE ? null : next)}
            disabledReason={disabledReason}
            data-attr="metrics-min-interval"
        />
    )
}
