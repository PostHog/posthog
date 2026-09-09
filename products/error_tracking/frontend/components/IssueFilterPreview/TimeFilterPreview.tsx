import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'

import { useSparklineDataIssueScene } from '../../hooks/use-sparkline-data'
import { useSparklineEvents } from '../../hooks/use-sparkline-events'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { cancelEvent } from '../../utils'
import { SpikeDetailsPopover } from '../SpikeDetailsPopover'
import { errorTrackingVolumeSparklineLogic } from '../VolumeSparkline/errorTrackingVolumeSparklineLogic'
import type { SparklineDatum } from '../VolumeSparkline/types'
import { VolumeSparkline } from '../VolumeSparkline/VolumeSparkline'
import { issueFilterPreviewLogic } from './issueFilterPreviewLogic'
import { TimeFilterPreviewHeader } from './TimeFilterPreviewHeader'

export function TimeFilterPreview(): JSX.Element {
    const { issueId, spikeEvents } = useValues(errorTrackingIssueSceneLogic)
    const sparklineKey = issueId || 'issue-unknown'
    const { clickedSpike } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { setClickedSpike } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { applyDateRangeFilter } = useActions(issueFilterPreviewLogic)
    const sparklineData = useSparklineDataIssueScene()
    const sparklineEvents = useSparklineEvents()
    const sparklineContainerRef = useRef<HTMLDivElement | null>(null)

    const handleRangeSelect = useCallback(
        (startDate: Date, endDate: Date) => {
            setClickedSpike(null)
            applyDateRangeFilter({
                date_from: startDate.toISOString(),
                date_to: endDate.toISOString(),
            })
        },
        [applyDateRangeFilter, setClickedSpike]
    )

    const handleSpikeClick = useCallback(
        (datum: SparklineDatum, clientX: number, clientY: number) => {
            setClickedSpike({ datum, clientX, clientY })
        },
        [setClickedSpike]
    )

    const matchedSpikeEvent = useMemo<ErrorTrackingSpikeEvent | null>(() => {
        if (!clickedSpike || sparklineData.length < 2) {
            return null
        }
        const binSizeMs = sparklineData[1].date.getTime() - sparklineData[0].date.getTime()
        const binStart = clickedSpike.datum.date.getTime()
        return (
            (spikeEvents as ErrorTrackingSpikeEvent[]).find((spikeEvent) => {
                const detectedAt = new Date(spikeEvent.detected_at).getTime()
                return detectedAt >= binStart && detectedAt < binStart + binSizeMs
            }) ?? null
        )
    }, [clickedSpike, spikeEvents, sparklineData])

    return (
        <div className="relative flex flex-col">
            <TimeFilterPreviewHeader sparklineKey={sparklineKey} />
            <div
                onClick={cancelEvent}
                ref={sparklineContainerRef}
                className="relative flex h-56 w-full flex-col px-2 py-3"
            >
                <VolumeSparkline
                    data={sparklineData}
                    layout="detailed"
                    xAxis="full"
                    events={sparklineEvents}
                    sparklineKey={sparklineKey}
                    className="h-full"
                    onRangeSelect={handleRangeSelect}
                    onBucketClick={handleRangeSelect}
                    onSpikeClick={handleSpikeClick}
                />
            </div>
            {clickedSpike && (
                <SpikeDetailsPopover
                    datum={clickedSpike.datum}
                    clientX={clickedSpike.clientX}
                    clientY={clickedSpike.clientY}
                    spikeEvent={matchedSpikeEvent}
                    onClose={() => setClickedSpike(null)}
                    sparklineContainerRef={sparklineContainerRef}
                />
            )}
        </div>
    )
}
