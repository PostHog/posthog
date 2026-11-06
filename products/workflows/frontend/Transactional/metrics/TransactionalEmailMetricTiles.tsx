import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { MetricTile, buildMetricTiles } from './emailMetricTiles'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { TransactionalEmailMetricTile } from './TransactionalEmailMetricTile'

const TILE_COLOR: Record<MetricTile['key'], Parameters<typeof getColorVar>[0]> = {
    sent: 'data-color-1',
    delivered: 'success',
    bounced: 'danger',
    complained: 'warning',
}

function caption(tile: MetricTile, failed: number): string {
    if (tile.key === 'sent') {
        return failed > 0 ? `${humanFriendlyNumber(failed)} failed` : 'None failed'
    }
    return `${humanFriendlyNumber(tile.count)} of ${tile.baseLabel}`
}

export function TransactionalEmailMetricTiles(): JSX.Element | null {
    const { statsOverTime, statsOverTimeLoading, statsOverTimeFailed } = useValues(transactionalEmailMetricsLogic)
    const tiles = useMemo(() => (statsOverTime ? buildMetricTiles(statsOverTime) : null), [statsOverTime])
    const labels = useMemo(() => statsOverTime?.buckets.map((bucket) => bucket.start) ?? [], [statsOverTime])
    const failed = statsOverTime?.buckets.reduce((total, bucket) => total + bucket.counts.failed, 0) ?? 0

    if (statsOverTimeLoading) {
        return (
            <div className="grid grid-cols-2 @3xl:grid-cols-4 gap-2">
                {Array.from({ length: 4 }).map((_, index) => (
                    <LemonSkeleton key={index} className="h-36" />
                ))}
            </div>
        )
    }
    if (statsOverTimeFailed || !statsOverTime || !tiles) {
        return null
    }
    return (
        <div className="grid grid-cols-2 @3xl:grid-cols-4 gap-2" data-attr="transactional-email-metric-tiles">
            {tiles.map((tile) => (
                <TransactionalEmailMetricTile
                    key={tile.key}
                    tile={tile}
                    labels={labels}
                    interval={statsOverTime.interval}
                    timezone={statsOverTime.timezone}
                    color={tile.value ? getColorVar(TILE_COLOR[tile.key]) : getColorVar('muted')}
                    caption={caption(tile, failed)}
                />
            ))}
        </div>
    )
}
