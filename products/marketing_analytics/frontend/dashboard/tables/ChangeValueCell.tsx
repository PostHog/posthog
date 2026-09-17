import { IconTrending } from '@posthog/icons'

import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ComparedValue } from './breakdownTableColumn'

export type ChangeFormat = 'number' | 'percentage' | 'duration' | 'decimal'

const format = (value: number, kind: ChangeFormat): string => {
    switch (kind) {
        case 'percentage':
            return `${(value * 100).toFixed(1)}%`
        case 'duration':
            return humanFriendlyDuration(value) ?? String(value)
        case 'decimal':
            return value.toFixed(1)
        default:
            return humanFriendlyNumber(value)
    }
}

/** A rate moves in percentage points, not percent: 8% to 10% is +2pp, and calling that +25% invites
 * the reader to mix the two up.
 *
 * Returns null when the change rounds away at the precision shown, so the cell renders a flat
 * marker rather than a signed zero. */
const formatDelta = (difference: number, kind: ChangeFormat): string | null => {
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
        default:
            return size < 1 ? null : `${sign}${humanFriendlyNumber(size)}`
    }
}

export interface ChangeValueCellProps {
    value: ComparedValue | null
    compare: boolean
    kind?: ChangeFormat
    /** Up is bad for metrics like bounce rate. */
    reverseColors?: boolean
    /** Neither direction is good or bad, so the change stays grey. */
    neutral?: boolean
    tooltipContent?: React.ReactNode
}

/** The value with its change against the previous period spelled out, rather than an arrow whose
 * size the reader has to take on trust. */
export function ChangeValueCell({
    value,
    compare,
    kind = 'number',
    reverseColors,
    neutral,
    tooltipContent,
}: ChangeValueCellProps): JSX.Element {
    if (!value) {
        return <span className="text-muted">–</span>
    }

    const [current, previous] = value
    const hasComparison = previous !== null && compare
    const difference = hasComparison ? current - previous : null

    const delta = difference === null ? null : formatDelta(difference, kind)
    const moved = difference !== null && delta !== null
    const Icon = !moved ? IconTrendingFlat : difference > 0 ? IconTrending : IconTrendingDown
    const color =
        neutral || !moved
            ? getColorVar('muted')
            : difference > 0 !== !!reverseColors
              ? getColorVar('success')
              : getColorVar('danger')

    const body = (
        <span className="inline-flex items-center justify-end gap-1.5 tabular-nums">
            <span>{format(current, kind)}</span>
            {difference !== null && (
                // eslint-disable-next-line react/forbid-dom-props
                <span className="inline-flex items-center gap-0.5 text-xs" style={{ color }}>
                    <Icon />
                    {delta}
                </span>
            )}
        </span>
    )

    const tooltip =
        hasComparison && previous !== null ? (
            <div className="flex flex-col gap-1">
                <div>{`${format(previous, kind)} in the previous period`}</div>
                {tooltipContent ? <div>{tooltipContent}</div> : null}
            </div>
        ) : (
            tooltipContent
        )

    return tooltip ? <Tooltip title={tooltip}>{body}</Tooltip> : body
}
