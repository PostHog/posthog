import './SpikeStripes.scss'

import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import type { SparklineData } from './types'

export type SpikeStripesProps = {
    data: SparklineData
    /** The chart's `minBarSize`, so a floored tiny bar gets stripes over its whole rendered height. */
    minBarSize: number
    /** The chart's `barCornerRadius`, so the stripes don't spill past a bar's rounded cap. */
    cornerRadius: number
}

type StripeRect = { index: number; left: number; top: number; width: number; height: number }

/** Animated barber-pole stripes over the spike bars, matching the pre-quill d3 renderer.
 *
 *  A chart child rather than a quill bar fill because quill paints bars to a canvas it repaints only
 *  when something changes — a scrolling fill there would need a permanent rAF loop per chart, and the
 *  issues list renders one chart per row. As a DOM overlay the motion is a compositor-driven CSS
 *  animation instead, so it costs nothing per frame. The bar underneath stays quill's, painted solid
 *  in the spike color, which keeps the geometry and color authoritative and hides any edge fringe. */
export function SpikeStripes({ data, minBarSize, cornerRadius }: SpikeStripesProps): JSX.Element | null {
    const { scales, labels } = useChartLayout()

    const rects = useMemo(() => {
        const baseline = scales.y(0)
        const found: StripeRect[] = []
        data.forEach((datum, index) => {
            // A non-positive bucket has no bar to stripe. Guarding it also keeps the flooring below
            // from inventing a `minBarSize`-tall rect where quill draws nothing.
            if (!datum.isSpike || datum.value <= 0) {
                return
            }
            const label = labels[index]
            const center = scales.x(label)
            // For a single-series vertical bar chart `extent` is the band width, which is also the
            // bar width — quill's bar layer fills the whole band (the gap comes from `bandPadding`).
            const width = scales.extent?.(label)
            if (center == null || !width) {
                return
            }
            const top = Math.min(scales.y(datum.value), baseline - minBarSize)
            if (baseline - top <= 0) {
                return
            }
            found.push({ index, left: center - width / 2, top, width, height: baseline - top })
        })
        return found
    }, [data, labels, scales, minBarSize])

    if (rects.length === 0) {
        return null
    }

    return (
        <>
            {rects.map((rect) => (
                <div
                    key={rect.index}
                    data-attr="error-tracking-volume-spike-stripes"
                    className="VolumeSparklineSpikeStripes"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height,
                        borderRadius: cornerRadius,
                    }}
                />
            ))}
        </>
    )
}
