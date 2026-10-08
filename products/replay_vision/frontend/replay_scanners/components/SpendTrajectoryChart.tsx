import { memo, useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import type { VisionQuotaApi } from '../../generated/api.schemas'
import { formatCreditCount, formatCreditNumber } from '../../utils/credits'
import type { SpendSeries } from '../visionUsageLogic'
import { SpendTrajectoryMarkers } from './SpendTrajectoryMarkers'
import { type SpendMarkerTone, type SpendReferenceLabel, buildSpendTrajectory } from './spendTrajectoryTransforms'

const DANGER_VAR = 'var(--danger)'

const REFERENCE_LINE_VAR: Record<SpendMarkerTone, string> = {
    default: 'var(--primary)',
    muted: 'var(--muted)',
    danger: DANGER_VAR,
}

const handleChartError = makeChartErrorHandler('replay-vision-spend-trajectory')

const formatTooltipValue = (value: number): string => formatCreditCount(value)

// The canvas cannot paint `var(--x)`, so series colours resolve through the computed style.
const cssVarName = (value: string): string => value.replace(/^var\(--(.+)\)$/, '$1')

interface SpendTrajectoryChartProps {
    quota: VisionQuotaApi
    /** Settled credits per UTC day of the period, oldest first. */
    dailyCredits: SpendSeries
    /** Credits the period is projected to end on, already held at the limit where one applies. */
    projectedTotal: number
    /** When demand crosses the limit inside the period, the date the verdict computed for it. */
    capReachDate: dayjs.Dayjs | null
    /** CSS variable reference (`var(--success)`) for the projection line, matching the verdict status. */
    statusVar: string
}

function SpendTrajectoryChartInner({
    quota,
    dailyCredits,
    projectedTotal,
    capReachDate,
    statusVar,
}: SpendTrajectoryChartProps): JSX.Element {
    const theme = useChartTheme()

    const trajectory = useMemo(
        () =>
            buildSpendTrajectory({
                quota,
                dailyCredits,
                projectedTotal,
                capReachDate,
                statusColor: getColorVar(cssVarName(statusVar)),
                dangerColor: getColorVar(cssVarName(DANGER_VAR)),
            }),
        // `theme` re-resolves the colours when light and dark mode flip.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [quota, dailyCredits, projectedTotal, capReachDate, statusVar, theme]
    )
    const { cap, freeCredits, spentTotal, endValue, crossing, pausedAtLimit, periodEnd } = trajectory

    const referenceLabels = useMemo(() => {
        const labels: SpendReferenceLabel[] = []
        if (cap !== null) {
            labels.push({
                key: 'limit',
                value: cap,
                text: `Monthly limit · ${formatCreditNumber(cap)}`,
                tone: 'danger',
                position: 'start',
            })
        }
        if (freeCredits !== null) {
            labels.push({
                key: 'free',
                value: freeCredits,
                text: `Free credits · ${formatCreditNumber(freeCredits)}`,
                tone: 'muted',
                position: 'end',
            })
        }
        return labels
    }, [cap, freeCredits])

    const config = useChartConfig(
        () => ({
            xAxis: { timezone: 'UTC', interval: 'day' as const },
            yAxis: { format: 'short' as const },
            goalLines: referenceLabels.map((line) => ({
                value: line.value,
                color: REFERENCE_LINE_VAR[line.tone],
                showValueOnHover: false,
            })),
            curve: 'linear' as const,
            tooltip: { valueFormatter: formatTooltipValue },
        }),
        [referenceLabels]
    )

    const resetDay = periodEnd.format('MMM D')
    const crossingDay = crossing?.date.format('MMM D')
    const caption = crossingDay
        ? `Hits the limit around ${crossingDay}. Scanning pauses until ${resetDay}.`
        : pausedAtLimit
          ? `Scanning is paused at the limit until ${resetDay}.`
          : null
    const summary = crossing
        ? `Cumulative spend this period: ${formatCreditCount(spentTotal)} so far, projected to reach the ${formatCreditCount(crossing.value)} limit around ${crossingDay}`
        : `Cumulative spend this period: ${formatCreditCount(spentTotal)} so far, projected ${formatCreditCount(endValue)} by ${periodEnd.format('MMMM D')}${cap !== null ? `, limit ${formatCreditCount(cap)}` : ''}`

    return (
        <div className="flex flex-col gap-1">
            <p className="sr-only">{summary}</p>
            <div className="flex h-52 w-full flex-col">
                <TimeSeriesLineChart
                    series={trajectory.series}
                    labels={trajectory.labels}
                    theme={theme}
                    config={config}
                    dataAttr="spend-trajectory-chart"
                    onError={handleChartError}
                >
                    <SpendTrajectoryMarkers markers={trajectory.markers} referenceLabels={referenceLabels} />
                </TimeSeriesLineChart>
            </div>
            {caption && <p className="m-0 text-xs text-danger">{caption}</p>}
        </div>
    )
}

// Props are loader and selector outputs, so a scanner toggle re-rendering the tab need not redraw the chart.
export const SpendTrajectoryChart = memo(SpendTrajectoryChartInner)
