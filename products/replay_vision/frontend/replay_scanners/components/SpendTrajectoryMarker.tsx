/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useChartLayout } from '@posthog/quill-charts'

import { SPEND_TONE_CLASS, resolveLabelTop } from './spendTrajectoryCaptionLayout'
import type { SpendMarker } from './spendTrajectoryTransforms'

const LABEL_GAP = 9
const MIN_LEFT_TEXT_ROOM = 60
const CROSSING_TEXT_WIDTH = 90

interface SpendTrajectoryMarkerProps {
    marker: SpendMarker
    /** Pixel rows of the reference lines, lowest first, that the text must not sit on. */
    referenceYs: number[]
}

export function SpendTrajectoryMarker({ marker, referenceYs }: SpendTrajectoryMarkerProps): JSX.Element | null {
    const { scales, dimensions, series } = useChartLayout()
    const x = scales.x(marker.label)
    const y = scales.y(marker.value)
    if (x === undefined || !isFinite(x) || !isFinite(y)) {
        return null
    }
    const plotRight = dimensions.plotLeft + dimensions.plotWidth
    const color = series.find((s) => s.key === marker.seriesKey)?.color
    const textLeft =
        marker.key === 'crossing'
            ? x + CROSSING_TEXT_WIDTH > plotRight
            : marker.key === 'end' || x - dimensions.plotLeft >= MIN_LEFT_TEXT_ROOM
    return (
        <div data-attr={`spend-trajectory-marker-${marker.key}`}>
            <span
                className="absolute size-1.5 rounded-full -translate-x-1/2 -translate-y-1/2"
                style={{ left: x, top: y, background: color }}
            />
            <span
                className={`absolute text-xs leading-none whitespace-nowrap font-semibold -translate-y-1/2 ${
                    textLeft ? '-translate-x-full' : ''
                } ${SPEND_TONE_CLASS[marker.tone]}`}
                style={{
                    left: textLeft ? x - LABEL_GAP : x + LABEL_GAP,
                    top: resolveLabelTop(y, referenceYs, dimensions.plotTop),
                }}
            >
                {marker.text}
            </span>
        </div>
    )
}
