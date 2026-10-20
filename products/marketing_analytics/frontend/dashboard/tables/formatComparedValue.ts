import { getCurrencySymbol } from 'lib/utils/currency'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CurrencyCode } from '~/queries/schema/schema-general'

import type { ComparedValue } from './breakdownTableColumn'

export type ChangeFormat = 'number' | 'percentage' | 'duration' | 'decimal' | 'currency'

/** Cents matter on an average conversion value and are noise on a five-figure total, so the
 * precision follows the size rather than being fixed as `formatCurrency` fixes it. */
const money = (value: number, currency: CurrencyCode): string => {
    const { symbol, isPrefix } = getCurrencySymbol(currency)
    const decimals = Math.abs(value) >= 1000 ? 0 : 2
    const sign = value < 0 ? '-' : ''
    const amount = humanFriendlyNumber(Math.abs(value), decimals, decimals)
    return isPrefix ? `${sign}${symbol}${amount}` : `${sign}${amount} ${symbol}`
}

const format = (value: number, kind: ChangeFormat, currency: CurrencyCode): string => {
    switch (kind) {
        case 'percentage':
            return `${(value * 100).toFixed(1)}%`
        case 'duration':
            return humanFriendlyDuration(value) ?? String(value)
        case 'decimal':
            return value.toFixed(1)
        case 'currency':
            return money(value, currency)
        default:
            return humanFriendlyNumber(value)
    }
}

/** A rate moves in percentage points, not percent: 8% to 10% is +2pp, and calling that +25% invites
 * the reader to mix the two up.
 *
 * Returns null when the change rounds away at the precision shown, so the cell renders a flat
 * marker rather than a signed zero. */
const formatDelta = (difference: number, kind: ChangeFormat, currency: CurrencyCode): string | null => {
    const size = Math.abs(difference)
    const sign = difference > 0 ? '+' : '-'
    switch (kind) {
        case 'percentage': {
            const points = (size * 100).toFixed(1)
            return Number(points) === 0 ? null : `${sign}${points}pp`
        }
        case 'duration': {
            const seconds = Math.round(size)
            return seconds === 0 ? null : `${sign}${humanFriendlyDuration(seconds) ?? seconds}`
        }
        case 'decimal': {
            const decimals = size.toFixed(1)
            return Number(decimals) === 0 ? null : `${sign}${decimals}`
        }
        case 'currency':
            return size < 0.01 ? null : `${sign}${money(size, currency)}`
        default:
            return size < 1 ? null : `${sign}${humanFriendlyNumber(size)}`
    }
}

interface FormattedComparedValue {
    current: string
    previous: string | null
    difference: number | null
    delta: string | null
}

export function formatComparedValue(
    value: ComparedValue,
    compare: boolean,
    kind: ChangeFormat,
    currency: CurrencyCode
): FormattedComparedValue {
    const [current, previous] = value
    const hasComparison = previous !== null && compare
    const difference = hasComparison ? current - previous : null
    return {
        current: format(current, kind, currency),
        previous: hasComparison ? format(previous, kind, currency) : null,
        difference,
        delta: difference === null ? null : formatDelta(difference, kind, currency),
    }
}
