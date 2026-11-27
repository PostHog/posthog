import { IconTrending } from '@posthog/icons'
import { Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { getColorVar } from 'lib/colors'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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

type ChangeTone = 'muted' | 'success' | 'danger'

const QUILL_TONE_CLASS: Record<ChangeTone, string> = {
    muted: 'text-muted-foreground',
    success: 'text-success-foreground',
    danger: 'text-destructive-foreground',
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!value) {
        return <span className={todayRailNav ? 'text-muted-foreground' : 'text-muted'}>–</span>
    }

    const { current, previous, difference, delta } = formatComparedValue(value, compare, kind, currency)
    const moved = difference !== null && delta !== null
    const Icon = !moved ? IconTrendingFlat : difference > 0 ? IconTrending : IconTrendingDown
    const tone: ChangeTone = neutral || !moved ? 'muted' : difference > 0 !== !!reverseColors ? 'success' : 'danger'

    const body = (
        <span
            className="inline-flex max-w-full flex-wrap items-center justify-end gap-1.5 tabular-nums"
            tabIndex={previous !== null || tooltipContent ? 0 : undefined}
        >
            <span>{current}</span>
            {difference !== null &&
                (todayRailNav ? (
                    <span className={`inline-flex items-center gap-0.5 text-xs ${QUILL_TONE_CLASS[tone]}`}>
                        <Icon />
                        <span>{delta}</span>
                    </span>
                ) : (
                    // eslint-disable-next-line react/forbid-dom-props
                    <span className="inline-flex items-center gap-0.5 text-xs" style={{ color: getColorVar(tone) }}>
                        <Icon />
                        <span>{delta}</span>
                    </span>
                ))}
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

    if (!tooltip) {
        return body
    }

    return todayRailNav ? (
        <QuillTooltip>
            <TooltipTrigger render={body} />
            <TooltipContent>{tooltip}</TooltipContent>
        </QuillTooltip>
    ) : (
        <Tooltip title={tooltip}>{body}</Tooltip>
    )
}
