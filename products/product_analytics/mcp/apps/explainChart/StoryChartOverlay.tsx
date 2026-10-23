/* eslint-disable react/forbid-dom-props -- pixel positions from the chart's scales */
import { type ReactElement } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { type MarkerObstacles, placeMarkers, type Point } from './storyMarkerPlacement'
import type { StoryPage } from './storyPages'

// The brand orange in both themes, so the highlight never reads as one of the chart's series.
const HIGHLIGHT_COLOR = 'var(--primary-light)'
const MARKER_SIZE = 20
const MARKER_GAP = 12
const TAIL_SPREAD = 0.45
const TIP_CLEARANCE = 3
const FEATHER = 28
const MIN_REACH = 22
const BAR_PADDING = 4

interface Band {
    left: number
    right: number
}

export interface StoryChartOverlayProps {
    seriesKey: string
    pages: StoryPage[]
    /** The page whose stretch is lit: the one on show, or the one the pointer is over. */
    highlightedIndex: number
    activeIndex: number
    onSelect: (index: number) => void
}

export function StoryChartOverlay({
    seriesKey,
    pages,
    highlightedIndex,
    activeIndex,
    onSelect,
}: StoryChartOverlayProps): ReactElement | null {
    const { scales, dimensions, labels, series, theme, resolvePositionValue } = useChartLayout()
    const chartSeries = series.find((candidate) => candidate.key === seriesKey)
    const highlighted = pages[highlightedIndex]
    if (!chartSeries || !highlighted) {
        return null
    }

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const xAt = (index: number): number | null => {
        const label = labels[index]
        const x = label == null ? undefined : scales.x(label, chartSeries.key)
        return x == null || !isFinite(x) ? null : x
    }
    const first = xAt(0)
    const second = xAt(1)
    const step = first !== null && second !== null ? Math.abs(second - first) : plotWidth
    // A bar fills its slot. A lone point on a line needs its neighbours in view to read as a rise or a fall.
    const barWidth = labels[0] == null ? undefined : scales.extent?.(labels[0])
    const range = highlighted.range
    const isOnePoint = !!range && range[0] === range[1]
    const reach =
        barWidth !== undefined
            ? barWidth / 2 + (isOnePoint ? BAR_PADDING : 0)
            : isOnePoint
              ? Math.max(step, MIN_REACH)
              : step / 2

    const from = range ? xAt(range[0]) : null
    const to = range ? xAt(range[1]) : null
    const band: Band | null =
        from !== null && to !== null
            ? { left: Math.max(from - reach, plotLeft), right: Math.min(to + reach, plotRight) }
            : null
    const surface = theme.backgroundColor ?? 'var(--card)'
    const tint = (share: number): string => `color-mix(in srgb, ${HIGHLIGHT_COLOR} ${share}%, transparent)`
    const dims = band
        ? [
              { left: plotLeft, right: band.left, fadeLeft: false, fadeRight: true },
              { left: band.right, right: plotRight, fadeLeft: true, fadeRight: false },
          ]
        : []

    const yScaleOf = (target: typeof chartSeries): ((value: number) => number) =>
        (target.yAxisId && scales.yAxes?.[target.yAxisId]?.scale) || scales.y
    const yScale = yScaleOf(chartSeries)
    const anchors = pages.flatMap((page, index) => {
        const x = page.anchor === null ? null : xAt(page.anchor)
        if (page.anchor === null || x === null || x < plotLeft || x > plotRight) {
            return []
        }
        const y = yScale(resolvePositionValue(chartSeries, page.anchor))
        return isFinite(y) ? [{ page, index, x, y }] : []
    })

    const drawn = series.filter((candidate) => !candidate.visibility?.excluded)
    const pointsOf = (target: typeof chartSeries): Point[] =>
        labels.flatMap((label, index) => {
            const x = scales.x(label, target.key)
            const y = yScaleOf(target)(resolvePositionValue(target, index))
            return x != null && isFinite(x) && isFinite(y) ? [{ x, y }] : []
        })
    const zero = yScale(0)
    const baseline = isFinite(zero) ? zero : plotTop + plotHeight
    const obstacles: MarkerObstacles =
        barWidth !== undefined
            ? {
                  lines: [],
                  bars: drawn.flatMap((target) =>
                      pointsOf(target).map(({ x, y }) => ({
                          left: x - barWidth / 2,
                          right: x + barWidth / 2,
                          top: Math.min(y, baseline),
                          bottom: Math.max(y, baseline),
                      }))
                  ),
              }
            : { lines: drawn.map(pointsOf), bars: [] }
    const centers = placeMarkers(anchors, obstacles, {
        radius: MARKER_SIZE / 2,
        distance: MARKER_SIZE / 2 + MARKER_GAP,
        bounds: { left: plotLeft, top: 0, right: plotRight, bottom: plotTop + plotHeight },
    })
    const markers = anchors.map((anchor, index) => ({ ...anchor, center: centers[index]! }))

    const tailOf = ({ x, y, center }: (typeof markers)[number]): string => {
        // The base starts under the badge, so the tail grows out of its border in the same colour.
        const angle = Math.atan2(y - center.y, x - center.x)
        const inset = MARKER_SIZE / 2 - 1.5
        const points: [number, number][] = [
            [center.x + Math.cos(angle - TAIL_SPREAD) * inset, center.y + Math.sin(angle - TAIL_SPREAD) * inset],
            [center.x + Math.cos(angle + TAIL_SPREAD) * inset, center.y + Math.sin(angle + TAIL_SPREAD) * inset],
            [x - Math.cos(angle) * TIP_CLEARANCE, y - Math.sin(angle) * TIP_CLEARANCE],
        ]
        return points.map(([px, py]) => `${px - plotLeft},${py - plotTop}`).join(' ')
    }

    return (
        <div data-attr="explain-chart-overlay">
            {dims.map((dim, index) => {
                const width = Math.max(dim.right - dim.left, 0)
                const feather = Math.min(FEATHER, width / 2)
                return (
                    <div
                        key={index}
                        className="pointer-events-none absolute opacity-65 transition-[left,width] duration-500 ease-out motion-reduce:transition-none starting:opacity-0"
                        style={{
                            left: dim.left,
                            top: plotTop,
                            width,
                            height: plotHeight,
                            background: `linear-gradient(to right, ${dim.fadeLeft ? 'transparent' : surface}, ${surface} ${feather}px, ${surface} calc(100% - ${feather}px), ${dim.fadeRight ? 'transparent' : surface})`,
                        }}
                    />
                )
            })}
            {band && (
                <div
                    className="pointer-events-none absolute rounded-t-md border-x border-t-2 transition-[left,width] duration-500 ease-out motion-reduce:transition-none starting:opacity-0"
                    style={{
                        left: band.left,
                        top: plotTop,
                        width: band.right - band.left,
                        height: plotHeight,
                        borderColor: tint(45),
                        borderTopColor: HIGHLIGHT_COLOR,
                        background: `linear-gradient(to bottom, ${tint(20)}, ${tint(5)})`,
                    }}
                />
            )}
            <svg
                className="pointer-events-none absolute overflow-visible"
                style={{ left: plotLeft, top: plotTop, width: plotWidth, height: plotHeight }}
                aria-hidden
            >
                {markers.map((marker) => (
                    <polygon
                        key={marker.index}
                        points={tailOf(marker)}
                        fill={marker.index === activeIndex ? 'var(--foreground)' : 'var(--muted-foreground)'}
                    />
                ))}
            </svg>
            {markers.map(({ page, index, center }) => {
                const active = index === activeIndex
                return (
                    <button
                        key={index}
                        type="button"
                        data-hog-charts-interactive-overlay
                        data-attr="explain-chart-marker"
                        aria-label={`Chapter ${index}: ${page.title}`}
                        aria-current={active ? 'step' : undefined}
                        className={`pointer-events-auto absolute flex cursor-pointer items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-ring ${
                            active
                                ? 'border-foreground bg-foreground text-background'
                                : 'border-muted-foreground bg-card text-foreground hover:border-foreground'
                        }`}
                        style={{
                            left: center.x - MARKER_SIZE / 2,
                            top: center.y - MARKER_SIZE / 2,
                            width: MARKER_SIZE,
                            height: MARKER_SIZE,
                        }}
                        onClick={(event) => {
                            event.stopPropagation()
                            onSelect(index)
                        }}
                    >
                        {index}
                    </button>
                )
            })}
        </div>
    )
}
