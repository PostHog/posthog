import { IconTrending } from '@posthog/icons'

import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { CurrencyCode } from '~/queries/schema/schema-general'

import type { ComparedValue } from './breakdownTableColumn'
import { ChangeFormat, formatComparedValue } from './formatComparedValue'

export interface ChangeValueCellProps {
    value: ComparedValue | null
    compare: boolean
    kind?: ChangeFormat
    /** Up is bad for metrics like bounce rate. */
    reverseColors?: boolean
    /** Neither direction is good or bad, so the change stays grey. */
    neutral?: boolean
    tooltipContent?: React.ReactNode
    /** The project's currency, for the `currency` format. */
    currency: CurrencyCode
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
    currency,
}: ChangeValueCellProps): JSX.Element {
    if (!value) {
        return <span className="text-muted">–</span>
    }

    const { current, previous, difference, delta } = formatComparedValue(value, compare, kind, currency)
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
            <span>{current}</span>
            {difference !== null && (
                // eslint-disable-next-line react/forbid-dom-props
                <span className="inline-flex items-center gap-0.5 text-xs" style={{ color }}>
                    <Icon />
                    <span>{delta}</span>
                </span>
            )}
        </span>
    )

    const tooltip =
        previous !== null ? (
            <div className="flex flex-col gap-1">
                <div>{`${previous} in the previous period`}</div>
                {tooltipContent ? <div>{tooltipContent}</div> : null}
            </div>
        ) : (
            tooltipContent
        )

    return tooltip ? <Tooltip title={tooltip}>{body}</Tooltip> : body
}
