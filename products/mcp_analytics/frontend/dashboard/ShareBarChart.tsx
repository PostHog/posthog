import { type ReactNode, useCallback, useMemo } from 'react'

import { BarList, type BarListConfig, type ChartTheme, type Series, type TooltipContext } from '@posthog/quill-charts'

import { Link } from 'lib/lemon-ui/Link'

import { formatNumber } from './formatters'

export interface ShareBarRow<T> {
    key: string
    label: string
    icon?: ReactNode
    href?: string
    value: number
    color?: string
    meta: T
}

type ShareMeta<T> = T & { share: number }

const SHARE_ROW_HEIGHT_PX = 40
// Matches the scroller's pt-2, so that the visible height ends just above the next row's label.
const SHARE_LIST_TOP_PADDING_PX = 8

const SHARE_BAR_CONFIG: BarListConfig = {
    labelPosition: 'top',
    scale: 'total',
    valueDisplay: 'both',
    barHeight: 10,
    rowHeight: SHARE_ROW_HEIGHT_PX,
}

function formatCalls(value: number): string {
    return `${formatNumber(value)} ${value === 1 ? 'call' : 'calls'}`
}

export function ShareBarChart<T>({
    rows,
    totalCalls,
    theme,
    tooltip,
    fillHeight = false,
    maxVisibleRows,
    label,
}: {
    rows: ShareBarRow<T>[]
    totalCalls: number
    theme: ChartTheme
    tooltip: (ctx: TooltipContext<ShareMeta<T>>) => JSX.Element | null
    /** Fill the parent's height and scroll the rows. The parent must be a flex column. */
    fillHeight?: boolean
    /** Show this many rows and scroll the rest. A shorter list keeps its natural height. */
    maxVisibleRows?: number
    label?: string
}): JSX.Element {
    const series = useMemo<Series<ShareMeta<T>>[]>(
        () =>
            rows.map((row) => ({
                key: row.key,
                label: row.label,
                data: [row.value],
                color: row.color,
                meta: { ...row.meta, share: totalCalls > 0 ? (row.value / totalCalls) * 100 : 0 },
            })),
        [rows, totalCalls]
    )
    const rowByKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
    const renderLabel = useCallback(
        (s: Series<ShareMeta<T>>): ReactNode => {
            const row = rowByKey.get(s.key)
            return (
                <>
                    {row?.icon}
                    {row?.href ? (
                        <Link to={row.href} target="_blank" className="truncate">
                            {s.label}
                        </Link>
                    ) : (
                        <span className="truncate">{s.label}</span>
                    )}
                </>
            )
        },
        [rowByKey]
    )
    const barList = (
        <BarList
            series={series}
            theme={theme}
            total={totalCalls}
            config={SHARE_BAR_CONFIG}
            valueFormatter={formatCalls}
            renderLabel={renderLabel}
            tooltip={tooltip}
        />
    )
    if (maxVisibleRows !== undefined) {
        return (
            <div
                className="overflow-y-auto pt-2"
                style={{ maxHeight: SHARE_LIST_TOP_PADDING_PX + maxVisibleRows * SHARE_ROW_HEIGHT_PX }}
                translate="no"
                tabIndex={0}
                role="region"
                aria-label={label}
            >
                {barList}
            </div>
        )
    }
    if (!fillHeight) {
        return (
            <div translate="no" className="pt-2">
                {barList}
            </div>
        )
    }
    // The absolute scroller adds no height, so the chart beside it sets the row height. Keep min-h-60 below that chart's height.
    return (
        <div className="relative min-h-60 flex-1">
            <div
                className="absolute inset-0 overflow-y-auto pt-2"
                translate="no"
                tabIndex={0}
                role="region"
                aria-label={label}
            >
                {barList}
            </div>
        </div>
    )
}
