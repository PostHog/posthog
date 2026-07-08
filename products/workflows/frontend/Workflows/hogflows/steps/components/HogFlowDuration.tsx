import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

// Allow an empty numeric part so a cleared input keeps its unit instead of resetting to a default.
// Also tolerate a decimal in stored values (older workflows) so we can floor it on display rather than lose the unit.
const DURATION_REGEX = /^(\d*\.?\d*)([dhm])$/

const MIN_VALUE_FOR_DURATION_UNIT = 1

const MAX_VALUE_FOR_DURATION_UNIT: Record<string, number> = {
    d: 30,
    h: 24,
    m: 60,
}

// Type=number lets browsers accept ".", ",", "e", "+", "-" — none of which are valid for a whole-number duration
const BLOCKED_NUMBER_INPUT_KEYS = new Set(['.', ',', 'e', 'E', '+', '-'])

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

    // Keep undefined (empty field) distinct from a real number so clearing doesn't snap back to a default.
    // Floor any decimal so a stored value like "1.5d" shows as "1d" and gets rewritten to a whole number on next save.
    const numberValue = numberValueString === '' ? undefined : Math.floor(parseFloat(numberValueString))

    const clamp = (n: number): number =>
        Math.min(Math.max(MIN_VALUE_FOR_DURATION_UNIT, Math.floor(n)), MAX_VALUE_FOR_DURATION_UNIT[unit])

    return (
        <div className="flex gap-2">
            <LemonInput
                type="number"
                value={numberValue}
                min={MIN_VALUE_FOR_DURATION_UNIT}
                max={MAX_VALUE_FOR_DURATION_UNIT[unit]}
                step={1}
                onKeyDown={(e) => {
                    if (BLOCKED_NUMBER_INPUT_KEYS.has(e.key)) {
                        e.preventDefault()
                    }
                }}
                onChange={(v) => {
                    if (v == null || !Number.isFinite(v)) {
                        onChange(`${unit}`)
                        return
                    }
                    onChange(`${Math.floor(v)}${unit}`)
                }}
                onBlur={() => numberValue !== undefined && onChange(`${clamp(numberValue)}${unit}`)}
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
