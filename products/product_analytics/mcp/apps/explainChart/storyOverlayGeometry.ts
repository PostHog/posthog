import type { ChartDimensions, ChartLayoutContextValue, ResolvedSeries } from '@posthog/quill-charts'

import { type MarkerObstacles, placeMarkers, type Point } from './storyMarkerPlacement'
import type { StoryPage } from './storyPages'

export const MARKER_SIZE = 20
const MARKER_GAP = 12
const TAIL_SPREAD = 0.45
const TIP_CLEARANCE = 3
const MIN_REACH = 22
const BAR_PADDING = 4

export interface Band {
    left: number
    right: number
}

export interface Dim extends Band {
    fadeLeft: boolean
    fadeRight: boolean
}

export interface StoryMarker {
    page: StoryPage
    index: number
    x: number
    y: number
    center: Point
}

type Layout = ChartLayoutContextValue

function xAt({ labels, scales }: Layout, series: ResolvedSeries, index: number): number | null {
    const label = labels[index]
    const x = label == null ? undefined : scales.x(label, series.key)
    return x == null || !isFinite(x) ? null : x
}

function yScaleOf({ scales }: Layout, series: ResolvedSeries): (value: number) => number {
    return (series.yAxisId && scales.yAxes?.[series.yAxisId]?.scale) || scales.y
}

function barWidthOf({ labels, scales }: Layout): number | undefined {
    return labels[0] == null ? undefined : scales.extent?.(labels[0])
}

export function chapterBand(layout: Layout, series: ResolvedSeries, range: [number, number] | null): Band | null {
    const { plotLeft, plotWidth } = layout.dimensions
    const first = xAt(layout, series, 0)
    const second = xAt(layout, series, 1)
    const step = first !== null && second !== null ? Math.abs(second - first) : plotWidth
    // A bar fills its slot. A lone point on a line needs its neighbours in view to read as a rise or a fall.
    const barWidth = barWidthOf(layout)
    const isOnePoint = !!range && range[0] === range[1]
    const reach =
        barWidth !== undefined
            ? barWidth / 2 + (isOnePoint ? BAR_PADDING : 0)
            : isOnePoint
              ? Math.max(step, MIN_REACH)
              : step / 2

    const from = range ? xAt(layout, series, range[0]) : null
    const to = range ? xAt(layout, series, range[1]) : null
    return from !== null && to !== null
        ? { left: Math.max(from - reach, plotLeft), right: Math.min(to + reach, plotLeft + plotWidth) }
        : null
}

export function dimsAround(band: Band, { plotLeft, plotWidth }: ChartDimensions): Dim[] {
    return [
        { left: plotLeft, right: band.left, fadeLeft: false, fadeRight: true },
        { left: band.right, right: plotLeft + plotWidth, fadeLeft: true, fadeRight: false },
    ]
}

function obstaclesOf(layout: Layout, series: ResolvedSeries): MarkerObstacles {
    const { labels, scales, dimensions, resolvePositionValue } = layout
    const drawn = layout.series.filter((candidate) => !candidate.visibility?.excluded)
    const pointsOf = (target: ResolvedSeries): Point[] =>
        labels.flatMap((label, index) => {
            const x = scales.x(label, target.key)
            const y = yScaleOf(layout, target)(resolvePositionValue(target, index))
            return x != null && isFinite(x) && isFinite(y) ? [{ x, y }] : []
        })
    const barWidth = barWidthOf(layout)
    if (barWidth === undefined) {
        return { lines: drawn.map(pointsOf), bars: [] }
    }
    const zero = yScaleOf(layout, series)(0)
    const baseline = isFinite(zero) ? zero : dimensions.plotTop + dimensions.plotHeight
    return {
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
}

export function storyMarkers(layout: Layout, series: ResolvedSeries, pages: StoryPage[]): StoryMarker[] {
    const { plotLeft, plotTop, plotWidth, plotHeight } = layout.dimensions
    const yScale = yScaleOf(layout, series)
    const anchors = pages.flatMap((page, index) => {
        const x = page.anchor === null ? null : xAt(layout, series, page.anchor)
        if (page.anchor === null || x === null || x < plotLeft || x > plotLeft + plotWidth) {
            return []
        }
        const y = yScale(layout.resolvePositionValue(series, page.anchor))
        return isFinite(y) ? [{ page, index, x, y }] : []
    })
    const centers = placeMarkers(anchors, obstaclesOf(layout, series), {
        radius: MARKER_SIZE / 2,
        distance: MARKER_SIZE / 2 + MARKER_GAP,
        bounds: { left: plotLeft, top: 0, right: plotLeft + plotWidth, bottom: plotTop + plotHeight },
    })
    return anchors.map((anchor, index) => ({ ...anchor, center: centers[index]! }))
}

export function tailPoints({ x, y, center }: StoryMarker, { plotLeft, plotTop }: ChartDimensions): string {
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
