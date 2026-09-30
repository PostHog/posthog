import { useLayoutEffect, useRef, useState } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { SpendReferenceCaption } from './SpendReferenceCaption'
import { type CaptionLefts, LABEL_INSET, measureCaptionLefts } from './spendTrajectoryCaptionLayout'
import { SpendTrajectoryMarker } from './SpendTrajectoryMarker'
import type { SpendMarker, SpendReferenceLabel } from './spendTrajectoryTransforms'

interface SpendTrajectoryMarkersProps {
    markers: SpendMarker[]
    /** Drawn here instead of through the library label, whose background bubble would hide the line. */
    referenceLabels: SpendReferenceLabel[]
}

export function SpendTrajectoryMarkers({ markers, referenceLabels }: SpendTrajectoryMarkersProps): JSX.Element {
    const { scales, dimensions } = useChartLayout()
    const rootRef = useRef<HTMLDivElement>(null)
    const [captionLefts, setCaptionLefts] = useState<CaptionLefts>({})
    // Lowest line first, so a label pushed past one is then tested against the next one up.
    const referenceYs = referenceLabels.map((line) => scales.y(line.value)).sort((a, b) => b - a)

    // Text widths are only known once rendered, so captions are measured after layout and a covered one
    // moves along its line. Candidates come from the measured width, so this settles in one extra render.
    useLayoutEffect(() => {
        const root = rootRef.current
        if (!root) {
            return
        }
        const lineStart = dimensions.plotLeft + LABEL_INSET
        const lineEnd = dimensions.plotLeft + dimensions.plotWidth - LABEL_INSET
        const next = measureCaptionLefts(root, referenceLabels, lineStart, lineEnd)
        if (!next) {
            return
        }
        setCaptionLefts((prev) => (referenceLabels.some((line) => next[line.key] !== prev[line.key]) ? next : prev))
    }, [markers, referenceLabels, scales, dimensions])

    return (
        <div ref={rootRef} className="contents">
            {referenceLabels.map((line) => (
                <SpendReferenceCaption key={line.key} line={line} measuredLeft={captionLefts[line.key]} />
            ))}
            {markers.map((marker) => (
                <SpendTrajectoryMarker key={marker.key} marker={marker} referenceYs={referenceYs} />
            ))}
        </div>
    )
}
