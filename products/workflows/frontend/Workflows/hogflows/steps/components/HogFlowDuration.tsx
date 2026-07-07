import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

// Allow an empty numeric part so a cleared input keeps its unit instead of resetting to a default
const DURATION_REGEX = /^(\d*\.?\d*)([dhm])$/

const MAX_VALUE_FOR_DURATION_UNIT: Record<string, number> = {
    d: 30,
    h: 24,
    m: 60,
}

export function HogFlowDuration({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const parts = value.match(DURATION_REGEX)
    const numberValueString = parts?.[1] ?? ''
    const unit = parts?.[2] ?? 'm'

    // Keep undefined (empty field) distinct from a real number so clearing doesn't snap back to a default
    const numberValue = numberValueString === '' ? undefined : parseFloat(numberValueString)

    return (
        <div className="flex gap-2">
            <LemonInput
                type="number"
                value={numberValue}
                min={0}
                max={MAX_VALUE_FOR_DURATION_UNIT[unit]}
                onChange={(v) => onChange(`${v != null && Number.isFinite(v) ? v : ''}${unit}`)}
                onBlur={() =>
                    numberValue !== undefined &&
                    onChange(`${Math.min(Math.max(0, numberValue), MAX_VALUE_FOR_DURATION_UNIT[unit])}${unit}`)
                }
            />

            <LemonSelect
                options={[
                    { label: 'Minute(s)', value: 'm' },
                    { label: 'Hour(s)', value: 'h' },
                    { label: 'Day(s)', value: 'd' },
                ]}
                value={unit}
                onChange={(v) =>
                    onChange(
                        `${numberValue === undefined ? '' : Math.min(numberValue, MAX_VALUE_FOR_DURATION_UNIT[v])}${v}`
                    )
                }
            />
        </div>
    )
}
