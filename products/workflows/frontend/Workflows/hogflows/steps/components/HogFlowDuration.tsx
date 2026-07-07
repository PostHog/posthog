import { useEffect, useState } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

const DURATION_REGEX = /^(\d*\.?\d+)([dhm])$/

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
    const [, numberValueString, unit] = value.match(DURATION_REGEX) ?? ['', '10', 'm']
    const numberValue = parseFloat(numberValueString)

    // Hold the in-progress number locally so backspacing the field empty doesn't
    // round-trip through DURATION_REGEX and snap the unit and value back to the fallback.
    const [inputValue, setInputValue] = useState<number | undefined>(numberValue)

    // Keep the local input in sync when the value changes from outside (e.g. a unit
    // change that clamps the number, or the parent resetting the config).
    useEffect(() => {
        setInputValue(numberValue)
    }, [numberValue])

    const commit = (nextUnit: string): void => {
        // Empty input (backspaced to nothing) is undefined; treat it as 0.
        const clamped = Math.min(Math.max(0, inputValue ?? 0), MAX_VALUE_FOR_DURATION_UNIT[nextUnit])
        onChange(`${clamped}${nextUnit}`)
    }

    return (
        <div className="flex gap-2">
            <LemonInput
                type="number"
                value={inputValue}
                min={0}
                max={MAX_VALUE_FOR_DURATION_UNIT[unit]}
                // An empty field reads as NaN; store undefined so it stays cleared instead of resetting.
                onChange={(v) => setInputValue(v !== undefined && Number.isFinite(v) ? v : undefined)}
                onBlur={() => commit(unit)}
            />

            <LemonSelect
                options={[
                    { label: 'Minute(s)', value: 'm' },
                    { label: 'Hour(s)', value: 'h' },
                    { label: 'Day(s)', value: 'd' },
                ]}
                value={unit}
                onChange={(v) => commit(v)}
            />
        </div>
    )
}
