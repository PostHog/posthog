import { type ReactNode, useMemo } from 'react'

import { createTooltipDateFormatter, useChartTheme } from '@posthog/quill-charts'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EmailStatsIntervalEnumApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MetricTile } from './emailMetricTiles'

const SPARKLINE_HEIGHT = 160

function formatRate(value: number): string {
    return `${value.toFixed(value < 1 ? 2 : 1)}%`
}

export function TransactionalEmailMetricTile({
    tile,
    labels,
    interval,
    timezone,
    color,
    caption,
}: {
    tile: MetricTile
    labels: string[]
    interval: EmailStatsIntervalEnumApi
    timezone: string
    color: string
    caption: ReactNode
}): JSX.Element {
    const theme = useChartTheme()
    const formatLabel = useMemo(
        () => createTooltipDateFormatter({ interval, timezone, allDays: labels }),
        [interval, timezone, labels]
    )
    const isRate = tile.format === 'rate'
    return (
        <div
            className="flex min-w-0 flex-col rounded border bg-surface-primary py-3"
            data-attr={`transactional-email-metric-${tile.key}`}
        >
            <Metric
                className="px-3"
                value={tile.value ?? 0}
                data={tile.points}
                labels={labels}
                formatLabel={formatLabel}
                restingSubtitle={caption}
                theme={theme}
                color={color}
                change={tile.change === null ? null : { value: tile.change }}
                goodDirection={tile.goodDirection}
                formatChange={
                    isRate
                        ? (points) => `${points > 0 ? '+' : ''}${points.toFixed(points < 1 && points > -1 ? 2 : 1)} pts`
                        : undefined
                }
                formatValue={(value) =>
                    tile.value === null ? '–' : isRate ? formatRate(value) : humanFriendlyNumber(value)
                }
                sparklineHeight={SPARKLINE_HEIGHT}
                sparklineTooltip={
                    isRate
                        ? ({ dataIndex }) => (
                              <span className="text-xs">
                                  {humanFriendlyNumber(tile.counts[dataIndex] ?? 0)} of{' '}
                                  {humanFriendlyNumber(tile.bases[dataIndex] ?? 0)} {tile.baseLabel}
                              </span>
                          )
                        : undefined
                }
            >
                <MetricHeader>
                    <MetricTitle className="min-w-0">{tile.title}</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="mt-1" />
                <MetricSubtitle className="mt-1" />
                <MetricSparkline className="-mx-3 mt-2 h-16" />
            </Metric>
        </div>
    )
}
