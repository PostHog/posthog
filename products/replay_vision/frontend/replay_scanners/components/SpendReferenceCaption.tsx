/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useChartLayout } from '@posthog/quill-charts'

import { LABEL_INSET, SPEND_TONE_CLASS } from './spendTrajectoryCaptionLayout'
import type { SpendReferenceLabel } from './spendTrajectoryTransforms'

const LABEL_LINE_GAP = 3

interface SpendReferenceCaptionProps {
    line: SpendReferenceLabel
    /** Set once the caption has been measured and placed clear of the markers. */
    measuredLeft: number | undefined
}

export function SpendReferenceCaption({ line, measuredLeft }: SpendReferenceCaptionProps): JSX.Element | null {
    const { scales, dimensions } = useChartLayout()
    const y = scales.y(line.value)
    if (!isFinite(y) || y < dimensions.plotTop || y > dimensions.plotTop + dimensions.plotHeight) {
        return null
    }
    const plotRight = dimensions.plotLeft + dimensions.plotWidth
    const atEnd = measuredLeft === undefined && line.position === 'end'
    return (
        <span
            data-attr={`spend-trajectory-reference-label-${line.key}`}
            className={`absolute text-xs leading-none whitespace-nowrap font-semibold -translate-y-full ${
                atEnd ? '-translate-x-full' : ''
            } ${SPEND_TONE_CLASS[line.tone]}`}
            style={{
                left: measuredLeft ?? (atEnd ? plotRight - LABEL_INSET : dimensions.plotLeft + LABEL_INSET),
                top: y - LABEL_LINE_GAP,
            }}
        >
            {line.text}
        </span>
    )
}
