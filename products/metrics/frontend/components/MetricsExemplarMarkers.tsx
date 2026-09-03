import { Tooltip } from '@posthog/lemon-ui'
import { useChartLayout } from '@posthog/quill-charts'

import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { hexToRGBA } from 'lib/utils/colors'

export interface MetricsExemplar {
    /** Emission time of the traced sample, as epoch ms. */
    timeMs: number
    onClick: () => void
    /** Design-token color name. Defaults to 'brand-blue'; error-spike markers pass 'danger' so the
     * two kinds sharing this overlay stay distinguishable. */
    color?: string
    /** Shown in a hover tooltip and as the button's aria-label — what this dot is, before
     * the user clicks it. Required: an unlabeled dot on a chart is not self-explanatory. */
    tooltipLabel: string
}

const RADIUS = 4

/** Traced emissions as clickable dots along the baseline of the metrics chart — the metric→trace
 *  pivot without opening the Samples tab. */
export function MetricsExemplarMarkers({ exemplars }: { exemplars: MetricsExemplar[] }): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()

    if (!exemplars.length || labels.length === 0) {
        return null
    }

    const bucketTimes = labels.map((label) => dayjs(label).valueOf())
    const baseline = dimensions.plotTop + dimensions.plotHeight

    // `getColorVar` reads computed styles (a potential style recalc), so resolve each
    // distinct token once here rather than per marker — there are only a couple across
    // the whole overlay (default plus any caller override like 'danger').
    const resolvedColors = new Map<string, string>()
    const colorFor = (token: string): string => {
        let color = resolvedColors.get(token)
        if (color === undefined) {
            color = getColorVar(token)
            resolvedColors.set(token, color)
        }
        return color
    }

    return (
        <>
            {exemplars.map((exemplar, index) => {
                const x = exemplarX(exemplar.timeMs, bucketTimes, labels, scales.x)
                if (x === null) {
                    return null
                }
                const color = colorFor(exemplar.color ?? 'brand-blue')
                return (
                    <Tooltip key={`${exemplar.timeMs}-${index}`} title={exemplar.tooltipLabel}>
                        <button
                            type="button"
                            aria-label={exemplar.tooltipLabel}
                            data-attr="metrics-exemplar-marker"
                            onClick={(e) => {
                                e.stopPropagation()
                                exemplar.onClick()
                            }}
                            // Opts this marker out of the chart's own hover/tooltip tracking (see
                            // `useChartInteraction`'s `originatesInInteractiveOverlay`), so hovering
                            // the dot shows its own tooltip instead of the chart's nearest-point one.
                            data-hog-charts-interactive-overlay
                            className="absolute pointer-events-auto rounded-full border cursor-pointer transition-transform hover:scale-150"
                            style={{
                                left: x - RADIUS,
                                top: baseline - RADIUS,
                                width: RADIUS * 2,
                                height: RADIUS * 2,
                                backgroundColor: hexToRGBA(color, 0.85),
                                borderColor: color,
                            }}
                        />
                    </Tooltip>
                )
            })}
        </>
    )
}

/** Pixel x for a timestamp, linearly interpolated between the buckets bracketing it. */
function exemplarX(
    timeMs: number,
    bucketTimes: number[],
    labels: string[],
    xScale: (label: string) => number | undefined
): number | null {
    const last = bucketTimes.length - 1
    // Labels mark bucket starts, so the plotted range extends one bucket span past the last label.
    const bucketWidth = last > 0 ? bucketTimes[last] - bucketTimes[last - 1] : Infinity
    if (timeMs < bucketTimes[0] || timeMs >= bucketTimes[last] + bucketWidth) {
        return null
    }
    let index = last
    while (index > 0 && bucketTimes[index] > timeMs) {
        index--
    }
    const start = xScale(labels[index])
    if (start === undefined || !isFinite(start)) {
        return null
    }
    const end = index + 1 < labels.length ? xScale(labels[index + 1]) : undefined
    if (end === undefined || !isFinite(end)) {
        return start
    }
    const span = bucketTimes[index + 1] - bucketTimes[index]
    if (span <= 0) {
        return start
    }
    return start + ((timeMs - bucketTimes[index]) / span) * (end - start)
}
