import React from 'react'

import { useChartLayout, useRadialLayout } from 'lib/hog-charts'
import type { TooltipContext } from 'lib/hog-charts'

import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'

export interface PieTooltipProps {
    ctx: TooltipContext<TrendsSeriesMeta>
    valueFormatter: (value: number) => string
}

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

function formatPercent(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

/** Trends-flavored pie tooltip — matches Chart.js parity (label, formatted value, share-of-total). */
export function PieTooltip({ ctx, valueFormatter }: PieTooltipProps): React.ReactElement | null {
    const { theme } = useChartLayout()
    const { layout } = useRadialLayout()
    const entry = ctx.seriesData[0]
    if (!entry) {
        return null
    }
    const slice = layout.slices.find((s) => s.series.key === entry.series.key)
    const share = slice?.fraction ?? 0

    return (
        <div
            className="px-3 py-2 rounded-lg shadow-lg text-[13px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? DEFAULT_TOOLTIP_BG,
                color: theme.tooltipColor ?? DEFAULT_TOOLTIP_COLOR,
            }}
        >
            <div className="flex items-center gap-2 mb-1">
                <span
                    className="inline-block size-2 rounded-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: entry.color }}
                />
                <span className="font-semibold">{entry.series.label}</span>
            </div>
            <div className="flex items-center gap-2">
                <strong>{valueFormatter(entry.value)}</strong>
                {share > 0 ? <span className="opacity-70">({formatPercent(share)})</span> : null}
            </div>
        </div>
    )
}
