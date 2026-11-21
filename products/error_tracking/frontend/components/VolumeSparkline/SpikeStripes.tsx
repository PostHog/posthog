import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { cn } from 'lib/utils/css-classes'

import type { SparklineData } from './types'

export type SpikeStripesProps = {
    data: SparklineData
    /** The chart's `minBarSize`, so a floored tiny bar is striped over its full drawn height. */
    minBarSize: number
    /** The chart's `barCornerRadius`, so the stripes don't spill past a bar's rounded cap. */
    cornerRadius: number
}

type StripeRect = { index: number; left: number; top: number; width: number; height: number }

/** Animated stripes over the spike bars. A DOM overlay rather than a quill bar fill: quill's canvas
 *  repaints only on change, so a scrolling fill would need a permanent rAF loop per chart, and the
 *  issues list renders one per row. */
export function SpikeStripes({ data, minBarSize, cornerRadius }: SpikeStripesProps): JSX.Element | null {
    const { scales, labels } = useChartLayout()

    const rects = useMemo(() => {
        const baseline = scales.y(0)
        const found: StripeRect[] = []
        data.forEach((datum, index) => {
            // No bar to stripe, and skipping it stops the flooring below inventing one.
            if (!datum.isSpike || datum.value <= 0) {
                return
            }
            const label = labels[index]
            const center = scales.x(label)
            // Single-series vertical bars fill the whole band, so `extent` is the bar width.
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
                    // `bg-[size:12px_12px]` tiles one cell; at `auto` the tile is the bar's own box,
                    // so the repeat seam lands mid-pattern and scrolls an out-of-phase strip up.
                    // The animation (and its reduced-motion/snapshot opt-outs) lives on the
                    // `VolumeSparkline__spikeStripes` class in base.scss, beside its keyframes.
                    className={cn(
                        'VolumeSparkline__spikeStripes absolute pointer-events-none',
                        'bg-[repeating-linear-gradient(135deg,rgb(255_255_255/40%)_0_4.2426px,transparent_4.2426px_8.4853px)]',
                        'bg-[size:12px_12px]'
                    )}
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
