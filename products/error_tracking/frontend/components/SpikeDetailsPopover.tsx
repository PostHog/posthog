import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonBanner, LemonSkeleton, Popover } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { errorTrackingIssueQuery } from '../queries'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import type { SparklineData, SparklineDatum } from './VolumeSparkline/types'
import { VolumeSparkline } from './VolumeSparkline/VolumeSparkline'

const ZOOM_WINDOW_MINUTES = 120
const ZOOM_RESOLUTION = 30

export type SpikeDetailsPopoverProps = {
    datum: SparklineDatum
    clientX: number
    clientY: number
    spikeEvent: ErrorTrackingSpikeEvent | null
    onClose: () => void
    /** Element whose interior clicks should not close the popover (e.g., the parent sparkline). */
    sparklineContainerRef?: React.MutableRefObject<HTMLDivElement | null>
}

export function SpikeDetailsPopover({
    datum,
    clientX,
    clientY,
    spikeEvent,
    onClose,
    sparklineContainerRef,
}: SpikeDetailsPopoverProps): JSX.Element {
    const [anchorEl, setAnchorEl] = useState<HTMLDivElement | null>(null)
    const { issueId, filterTestAccounts, filterGroup, searchQuery } = useValues(errorTrackingIssueSceneLogic)

    const [zoomData, setZoomData] = useState<SparklineData | null>(null)
    const [loading, setLoading] = useState(true)
    const [hasZoomError, setHasZoomError] = useState(false)

    const center = useMemo(() => dayjs(spikeEvent?.detected_at ?? datum.date), [spikeEvent, datum])
    const zoomDateFrom = useMemo(() => center.subtract(ZOOM_WINDOW_MINUTES / 2, 'minute'), [center])
    const zoomDateTo = useMemo(() => center.add(ZOOM_WINDOW_MINUTES / 2, 'minute'), [center])

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setHasZoomError(false)
        setZoomData(null)
        const run = async (): Promise<void> => {
            try {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId,
                        dateRange: {
                            date_from: zoomDateFrom.toISOString(),
                            date_to: zoomDateTo.toISOString(),
                        },
                        filterTestAccounts,
                        filterGroup,
                        searchQuery,
                        volumeResolution: ZOOM_RESOLUTION,
                        withAggregations: true,
                    }),
                    { refresh: 'blocking' }
                )
                if (cancelled) {
                    return
                }
                const aggregations: ErrorTrackingIssueAggregations | undefined =
                    response.results?.[0]?.aggregations ?? undefined
                const buckets = aggregations?.volume_buckets ?? []
                setZoomData(buckets.map(({ label, value }) => ({ value, date: new Date(label) })))
            } catch {
                if (!cancelled) {
                    setZoomData(null)
                    setHasZoomError(true)
                }
            } finally {
                if (!cancelled) {
                    setLoading(false)
                }
            }
        }
        void run()
        return () => {
            cancelled = true
        }
    }, [issueId, filterTestAccounts, filterGroup, searchQuery, zoomDateFrom, zoomDateTo])

    const occurrencesDuringSpike = spikeEvent?.current_bucket_value ?? datum.value
    const baseline = spikeEvent?.computed_baseline ?? null
    const multiplier = baseline && baseline > 0 ? occurrencesDuringSpike / baseline : null

    return (
        <>
            <div
                ref={setAnchorEl}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    left: clientX,
                    top: clientY,
                    width: 1,
                    height: 1,
                    pointerEvents: 'none',
                }}
            />
            <Popover
                visible
                onClickOutside={onClose}
                referenceElement={anchorEl}
                placement="right-start"
                fallbackPlacements={['left-start', 'top', 'bottom']}
                showArrow
                padded={false}
                additionalRefs={sparklineContainerRef ? [sparklineContainerRef] : []}
                overlay={
                    <div className="flex flex-col w-[360px] gap-2 p-3">
                        <div className="flex items-center justify-between">
                            <div className="text-xs font-semibold text-warning-dark">Spike details</div>
                            <div className="text-xs text-muted">{center.utc().format('D MMM YYYY HH:mm (UTC)')}</div>
                        </div>
                        <div className="text-xs text-muted">{ZOOM_WINDOW_MINUTES}-minute window centered on spike</div>
                        <div className="h-[120px] w-full">
                            {hasZoomError ? (
                                <LemonBanner type="error" className="mb-0 h-full min-h-0 text-xs">
                                    Could not load the volume window for this spike. Try again or open the full issue
                                    view.
                                </LemonBanner>
                            ) : loading || !zoomData ? (
                                <LemonSkeleton className="w-full h-full" />
                            ) : (
                                <VolumeSparkline
                                    data={zoomData}
                                    layout="detailed"
                                    xAxis="full"
                                    sparklineKey={`spike-zoom-${issueId}-${center.valueOf()}`}
                                    className="h-full"
                                />
                            )}
                        </div>
                        <div className="grid grid-cols-3 gap-2 pt-1">
                            <SpikeMetric label="Occurrences" value={humanFriendlyLargeNumber(occurrencesDuringSpike)} />
                            <SpikeMetric
                                label="Baseline"
                                value={baseline == null ? '—' : humanFriendlyLargeNumber(Math.round(baseline))}
                            />
                            <SpikeMetric
                                label="Exceeded by"
                                value={multiplier == null ? '—' : `${multiplier.toFixed(1)}x`}
                            />
                        </div>
                    </div>
                }
            />
        </>
    )
}

function SpikeMetric({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <div className="text-base font-bold leading-tight">{value}</div>
            <div className="text-xs text-muted">{label}</div>
        </div>
    )
}
