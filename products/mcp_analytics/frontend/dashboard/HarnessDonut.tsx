import { useCallback, useMemo } from 'react'

import {
    type ChartTheme,
    PieChart,
    type PieChartConfig,
    type Series,
    type TooltipContext,
    useRadialLayout,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import { Card } from './Card'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { HarnessPill } from './harness'
import { harnessLogo, harnessSliceColor } from './harnessRegistry'

const HARNESS_DONUT_CONFIG: PieChartConfig = {
    innerRadiusRatio: 0.6,
    // Built-in text labels are off — HarnessSliceLabels draws logo pills instead.
    showLabelOnSlice: false,
    showValueOnSlice: false,
}

// Slices smaller than this don't get a logo overlay — it wouldn't fit on the arc.
const MIN_LABELLED_SLICE_FRACTION = 0.05

// Rendered as a PieChart child so it can read the slice geometry from the radial layout context.
function HarnessSliceLabels(): JSX.Element | null {
    const { layout } = useRadialLayout()
    const midRadius = layout.innerRadius + (layout.outerRadius - layout.innerRadius) / 2
    return (
        <>
            {layout.slices.map((slice) => {
                if (slice.fraction < MIN_LABELLED_SLICE_FRACTION) {
                    return null
                }
                const x = layout.cx + Math.sin(slice.centroidAngle) * midRadius
                const y = layout.cy - Math.cos(slice.centroidAngle) * midRadius
                const category = slice.series.label
                const logo = harnessLogo(category)
                return (
                    <div
                        key={slice.series.key}
                        className="pointer-events-none absolute"
                        style={{ left: x, top: y, transform: 'translate(-50%, -50%)' }}
                    >
                        {logo ? (
                            <img
                                src={logo.src}
                                alt={logo.alt}
                                title={category}
                                className="h-7 w-7 object-contain"
                                style={{ filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.45))' }}
                            />
                        ) : (
                            <HarnessPill category={category} />
                        )}
                    </div>
                )
            })}
        </>
    )
}

export function HarnessDonut({
    rows,
    loading,
    theme,
}: {
    rows: HarnessRow[]
    loading: boolean
    theme: ChartTheme
}): JSX.Element {
    const totalCalls = rows.reduce((acc, r) => acc + r.total_calls, 0)
    const series = useMemo<Series<HarnessRow>[]>(
        () =>
            rows.map((r, i) => ({
                key: r.category,
                label: r.category,
                color: harnessSliceColor(theme, r.category, i),
                data: [r.total_calls],
                meta: r,
            })),
        [rows, theme]
    )
    const renderTooltip = useCallback((ctx: TooltipContext<HarnessRow>): JSX.Element | null => {
        const entry = ctx.seriesData[0]
        const row = entry?.series.meta
        if (!row) {
            return null
        }
        const share = entry.fraction !== undefined ? entry.fraction * 100 : 0
        return (
            <ChartTooltip
                title={row.category}
                rows={[
                    ['Calls', String(row.total_calls)],
                    ['Share', formatPercentage(share, { compact: true })],
                    ['Sessions', String(row.sessions)],
                    ['Error rate', formatPercentage(row.error_rate_pct, { compact: true })],
                ]}
            />
        )
    }, [])

    if (loading && rows.length === 0) {
        return (
            <Card className="flex flex-1 flex-col" title="Share of calls by harness">
                <div className="flex min-h-[300px] flex-1 items-center justify-center">
                    <Skeleton className="h-[180px] w-[180px] rounded-full" />
                </div>
            </Card>
        )
    }
    if (rows.length === 0) {
        return (
            <Card className="flex flex-1 flex-col" title="Share of calls by harness">
                <div className="flex min-h-[300px] flex-1 items-center justify-center text-[12px] text-secondary">
                    No harness data yet.
                </div>
            </Card>
        )
    }

    return (
        <Card className="flex flex-1 flex-col" title="Share of calls by harness">
            <div className="flex min-h-[300px] flex-1 flex-col">
                <PieChart<HarnessRow>
                    series={series}
                    theme={theme}
                    config={HARNESS_DONUT_CONFIG}
                    tooltip={renderTooltip}
                    centerLabel={
                        <div className="text-center">
                            <div className="text-3xl font-semibold text-primary">{formatNumber(totalCalls)}</div>
                            <div className="text-xs text-secondary">calls</div>
                        </div>
                    }
                >
                    <HarnessSliceLabels />
                </PieChart>
            </div>
        </Card>
    )
}
