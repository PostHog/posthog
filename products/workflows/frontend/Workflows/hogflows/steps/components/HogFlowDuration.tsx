import { useEffect, useRef, useState } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

// Allow an empty numeric part so a cleared input keeps its unit instead of resetting to a default.
const DURATION_REGEX = /^(\d*\.?\d*)([dhms])$/

const MAX_VALUE_FOR_DURATION_UNIT: Record<string, number> = {
    d: 30,
    h: 24,
    m: 60,
    s: 60,
}

// Type=number lets browsers accept "e", "+" and "-", none of which the executor's duration parser
// understands. "." and "," stay allowed because fractional durations like 1.5d are valid, and "," is
// the decimal separator the browser expects in some locales.
const BLOCKED_NUMBER_INPUT_KEYS = new Set(['e', 'E', '+', '-'])

// A float stringifies to exponent notation at both extremes ("1e-7", "1e+21") and every duration
// parser in the stack reads fixed point only, so round the amount to a fixed number of decimals and
// treat magnitudes that toFixed itself exponentiates as the unit's maximum.
const MAX_FRACTION_DIGITS = 6
const EXPONENT_THRESHOLD = 1e21

export function HogFlowDuration({
    value,
    onChange,
    allowUnbounded = false,
}: {
    value: string
    onChange: (value: string) => void
    // The per-unit ceilings bound how long a fixed delay waits. A date offset is bounded by the
    // step's max_delay_duration instead, so it opts out and keeps its full magnitude ("45 days before").
    allowUnbounded?: boolean
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)
    const parts = value.match(DURATION_REGEX)
    const numberValueString = parts?.[1] ?? ''
    const unit = parts?.[2] ?? 'm'

    // Keep undefined (empty field) distinct from a real number so clearing doesn't snap back to a default.
    const parsedNumber = parseFloat(numberValueString)
    const numberValue = Number.isFinite(parsedNumber) ? parsedNumber : undefined

    // The parent commits config through an async kea listener, so binding the field straight to the derived
    // value re-applies the previous digit for one render and swallows a keystroke on clear. Mirror it locally
    // so the user's edit shows immediately; reconcile only when the derived value changes externally (unit
    // clamp, switching nodes). NaN (not undefined) keeps LemonInput controlled when empty.
    const [displayNumber, setDisplayNumber] = useState(numberValue)
    useEffect(() => {
        setDisplayNumber(numberValue)
    }, [numberValue])

    // Holds an amount to the unit's ceiling, unless the field opts out (a date offset).
    const capToUnit = (n: number, u: string): number =>
        allowUnbounded ? n : Math.min(n, MAX_VALUE_FOR_DURATION_UNIT[u])

    // Fractions are allowed, so the only lower bound is "greater than zero". Anything at or below it
    // would save a delay that never waits, so snap those back up to one whole unit.
    const clamp = (n: number): number => (n > 0 ? capToUnit(n, unit) : 1)

    const normalizeAmount = (n: number): number =>
        n >= EXPONENT_THRESHOLD ? MAX_VALUE_FOR_DURATION_UNIT[unit] : Number(n.toFixed(MAX_FRACTION_DIGITS))

    return (
        <div className="flex gap-2">
            <LemonInput
                type="number"
                inputRef={inputRef}
                value={displayNumber ?? NaN}
                min={0}
                max={allowUnbounded ? undefined : MAX_VALUE_FOR_DURATION_UNIT[unit]}
                step="any"
                onKeyDown={(e) => {
                    if (BLOCKED_NUMBER_INPUT_KEYS.has(e.key)) {
                        e.preventDefault()
                    }
                }}
                onChange={(v) => {
                    if (v == null || !Number.isFinite(v)) {
                        // An empty value with NaN means either the field was cleared or the browser
                        // cannot parse what is in it, and only validity.badInput separates the two. A
                        // lone "." lands in the second case, so hold the committed duration instead of
                        // overwriting it with a unit that carries no number.
                        if (inputRef.current?.validity.badInput) {
                            return
                        }
                        setDisplayNumber(undefined)
                        onChange(`${unit}`)
                        return
                    }
                    const next = normalizeAmount(v)
                    setDisplayNumber(next)
                    onChange(`${next}${unit}`)
                }}
                onBlur={() => displayNumber !== undefined && onChange(`${clamp(displayNumber)}${unit}`)}
            />

            <LemonSelect
                options={[
                    { label: 'Second(s)', value: 's' },
                    { label: 'Minute(s)', value: 'm' },
                    { label: 'Hour(s)', value: 'h' },
                    { label: 'Day(s)', value: 'd' },
                ]}
                value={unit}
                onChange={(v) => onChange(`${displayNumber === undefined ? '' : capToUnit(displayNumber, v)}${v}`)}
            />
        </div>
    )
}
