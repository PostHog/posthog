// The one duration grammar the builder validates against. The executor and the API enforce the same
// one (products/workflows/backend/utils/durations.py), so a value this accepts is a value they accept.
// The alternation is linear; `\d*\.?\d+` backtracks quadratically on a long run of digits.
const DURATION_BODY = '(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+)'

export const DURATION_UNITS = ['d', 'h', 'm', 's'] as const
export type DurationUnit = (typeof DURATION_UNITS)[number]

const DURATION_REGEX = new RegExp(`^${DURATION_BODY}[dhms]$`)
const SIGNED_DURATION_REGEX = new RegExp(`^(-?)(${DURATION_BODY})([dhms])$`)

// An amount is allowed to be empty here, which no other matcher permits: a field the user has cleared
// still has to keep its unit rather than snap back to a default. The result is an edit in progress,
// never a duration to store.
const PARTIAL_DURATION_REGEX = /^([0-9]*\.?[0-9]*)([dhms])$/

export interface ParsedDuration {
    amount: number
    /** The amount exactly as written, so round-tripping a value does not restyle it. */
    amountText: string
    unit: DurationUnit
    negative: boolean
}

export function isDuration(value: string): boolean {
    return DURATION_REGEX.test(value)
}

export function isSignedDuration(value: string): boolean {
    return SIGNED_DURATION_REGEX.test(value)
}

export function parseDuration(value: string): ParsedDuration | null {
    const parts = SIGNED_DURATION_REGEX.exec(value)
    if (!parts) {
        return null
    }
    return {
        amount: parseFloat(parts[2]),
        amountText: parts[2],
        unit: parts[3] as DurationUnit,
        negative: parts[1] === '-',
    }
}

/** Splits a field the user is still editing. Says nothing about whether the value is storable. */
export function splitPartialDuration(value: string): { amountText: string; unit: DurationUnit } {
    const parts = PARTIAL_DURATION_REGEX.exec(value)
    return { amountText: parts?.[1] ?? '', unit: (parts?.[2] as DurationUnit) ?? 'm' }
}
