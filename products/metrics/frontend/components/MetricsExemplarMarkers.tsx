import { useChartLayout } from '@posthog/quill-charts'

import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { hexToRGBA } from 'lib/utils/colors'

export interface MetricsExemplar {
    /** Emission time of the traced sample, as epoch ms. */
    timeMs: number
    onClick: () => void
}

const RADIUS = 4

/** Traced emissions as clickable dots along the baseline of the metrics chart — the metric→trace
 *  pivot without opening the Samples tab. Renders as a child of a quill chart, positioning each dot
 *  by interpolating its timestamp between the two buckets bracketing it, so a dot sits where the
 *  emission actually happened rather than snapping to a bucket. */
export function MetricsExemplarMarkers({ exemplars }: { exemplars: MetricsExemplar[] }): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()

    if (!exemplars.length || labels.length === 0) {
        return null
    }

    const bucketTimes = labels.map((label) => dayjs(label).valueOf())
    const color = getColorVar('primary')
    const baseline = dimensions.plotTop + dimensions.plotHeight

    return (
        <>
            {exemplars.map((exemplar, index) => {
                const x = exemplarX(exemplar.timeMs, bucketTimes, labels, scales.x)
                if (x === null) {
                    return null
                }
                return (
                    <button
                        key={`${exemplar.timeMs}-${index}`}
                        type="button"
                        aria-label={`Open the trace emitted at ${dayjs(exemplar.timeMs).format('D MMM YYYY HH:mm:ss')}`}
                        data-attr="metrics-exemplar-marker"
                        onClick={exemplar.onClick}
                        className="absolute rounded-full border cursor-pointer transition-transform hover:scale-150"
                        style={{
                            left: x - RADIUS,
                            top: baseline - RADIUS,
                            width: RADIUS * 2,
                            height: RADIUS * 2,
                            backgroundColor: hexToRGBA(color, 0.85),
                            borderColor: color,
                        }}
                    />
                )
            })}
        </>
    )
}

/** Pixel x for a timestamp, linearly interpolated between the buckets bracketing it. Null when the
 *  timestamp falls outside the plotted range or its bucket has no resolvable position. */
function exemplarX(
    timeMs: number,
    bucketTimes: number[],
    labels: string[],
    xScale: (label: string) => number | undefined
): number | null {
    if (timeMs < bucketTimes[0] || timeMs > bucketTimes[bucketTimes.length - 1]) {
        return null
    }
    let index = bucketTimes.length - 1
    while (index > 0 && bucketTimes[index] > timeMs) {
        index--
    }
    const start = xScale(labels[index])
    if (start === undefined || !isFinite(start)) {
        return null
    }
    const span = bucketTimes[index + 1] - bucketTimes[index]
    const end = index + 1 < labels.length ? xScale(labels[index + 1]) : undefined
    if (end === undefined || !isFinite(end) || span <= 0) {
        return start
    }
    return start + ((timeMs - bucketTimes[index]) / span) * (end - start)
}
