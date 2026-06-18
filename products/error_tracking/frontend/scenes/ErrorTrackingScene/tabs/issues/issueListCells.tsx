import { useValues } from 'kea'
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { errorTrackingVolumeSparklineLogic } from 'products/error_tracking/frontend/components/VolumeSparkline/errorTrackingVolumeSparklineLogic'
import {
    formatCompactVolumeHoverDate,
    formatCompactVolumeHoverOccurrences,
} from 'products/error_tracking/frontend/components/VolumeSparkline/formatCompactVolumeHover'
import { VolumeSparkline } from 'products/error_tracking/frontend/components/VolumeSparkline/VolumeSparkline'
import { applyVolumeSpikeHighlights, useSparklineData } from 'products/error_tracking/frontend/hooks/use-sparkline-data'
import { batchSpikeEventsLogic } from 'products/error_tracking/frontend/logics/batchSpikeEventsLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION } from 'products/error_tracking/frontend/utils'

export type IssueCountColumn = 'occurrences' | 'sessions' | 'users'

/** Single aggregation count for an issue (occurrences / sessions / users). */
export const IssueCountCell = ({
    record,
    columnName,
}: {
    record: ErrorTrackingIssue
    columnName: IssueCountColumn
}): JSX.Element => {
    const count = record.aggregations ? record.aggregations[columnName] : 0

    return (
        <span className="text-lg font-medium">
            {columnName === 'sessions' && count === 0 ? (
                <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                    -
                </Tooltip>
            ) : (
                humanFriendlyLargeNumber(count)
            )}
        </span>
    )
}

/** Compact volume sparkline + hovered-bin readout for an issue row. */
export const IssueVolumeCell = ({ record }: { record: ErrorTrackingIssue }): JSX.Element => {
    if (!record.aggregations) {
        throw new Error('No aggregations found')
    }
    const sparklineKey = record.id ?? 'issue-unknown'
    const baseData = useSparklineData(record.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    const { spikeEventsByIssueId } = useValues(batchSpikeEventsLogic)
    const spikeEvents = useMemo(
        () => (record.id ? (spikeEventsByIssueId[record.id] ?? []) : []),
        [record.id, spikeEventsByIssueId]
    )
    const data = useMemo(() => applyVolumeSpikeHighlights(baseData, spikeEvents), [baseData, spikeEvents])

    const { hoveredDatum, isBarHighlighted } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))

    return (
        <div className="flex w-full min-w-0 justify-center">
            <div className="flex w-56 max-w-full min-w-0 flex-col">
                <div className="h-12 min-h-12 w-full">
                    <VolumeSparkline
                        className="h-full"
                        data={data}
                        layout="compact"
                        xAxis="minimal"
                        sparklineKey={sparklineKey}
                    />
                </div>
                <div
                    className={cn(
                        'flex h-3 w-full items-center justify-between gap-1 px-px text-[9px] leading-none text-muted',
                        isBarHighlighted ? 'opacity-100' : 'opacity-0'
                    )}
                >
                    <span className="min-w-0 truncate">
                        {hoveredDatum ? formatCompactVolumeHoverDate(hoveredDatum) : '\u00a0'}
                    </span>
                    <span className="min-w-0 shrink-0 text-right tabular-nums">
                        {hoveredDatum ? formatCompactVolumeHoverOccurrences(hoveredDatum) : '\u00a0'}
                    </span>
                </div>
            </div>
        </div>
    )
}
