import { lineHeight } from '@/ui/tokens'

import type { ChartAxisData } from './chartAxes'

import {
    BAR_MIN_HEIGHT,
    formatAxisDate,
    monoTextWidth,
    TICK_FONT_SIZE,
    TICK_GAP,
    xTickIndices,
    yAxisTicks,
} from './chartMath'
import type { ChartInterval, ChartKind, ChartVariant } from './types'

export const TICK_LINE_HEIGHT = lineHeight(TICK_FONT_SIZE)
export const X_LABEL_OFFSET = 6
const PLOT_TOP = Math.ceil(TICK_LINE_HEIGHT / 2)
const PLOT_BOTTOM = Math.ceil(TICK_LINE_HEIGHT) + X_LABEL_OFFSET
// Room for the selection dot on the last bucket, which is the one people check most.
const PLOT_RIGHT = 6
// Wider than the text, so a small error in the width estimate cannot wrap or truncate it.
const X_LABEL_SLACK = 8
const COMPACT_Y_TICKS = 3

export interface PlotRect {
    left: number
    right: number
    top: number
    bottom: number
}

export interface ChartGeometry {
    width: number
    height: number
    plot: PlotRect
    /** The x of each bucket's center. */
    xs: number[]
    yDomain: [number, number]
    /** Gridlines, with their labels when the variant shows y labels. */
    yTicks: { value: number; y: number; text: string | null }[]
    yLabelWidth: number
    rightYDomain?: [number, number]
    rightYTicks?: { value: number; y: number; text: string | null }[]
    rightYLabelWidth?: number
    xLabels: { index: number; left: number; width: number; text: string }[]
    /** The slot each bar sits in. */
    bandWidth: number
}

export interface GeometryInput {
    width: number
    height: number
    kind: ChartKind
    variant: ChartVariant
    count: number
    /** Every visible value, across series. The y axis fits them. */
    values: number[]
    dates: number[]
    labels?: (string | undefined)[]
    primaryAxis?: ChartAxisData
    rightAxis?: ChartAxisData
    interval: ChartInterval
    uses24hourClock: boolean
    formatValue: (value: number) => string
}

export function yPosition(value: number, domain: [number, number], plot: PlotRect): number {
    'worklet'
    const [lo, hi] = domain
    const span = hi - lo || 1
    return plot.bottom - ((value - lo) / span) * (plot.bottom - plot.top)
}

export function barSpan(valueY: number, zeroY: number): { top: number; height: number } {
    'worklet'
    const offset = valueY - zeroY
    const height = offset === 0 ? 0 : Math.max(BAR_MIN_HEIGHT, Math.abs(offset))
    return { top: offset > 0 ? zeroY : zeroY - height, height }
}

/**
 * Scales computed during render, so a chart draws in the first render after layout instead of waiting for
 * victory-native to report its scales back.
 */
export function chartGeometry(input: GeometryInput): ChartGeometry {
    const { width, height, kind, variant, count, values, dates, interval, formatValue } = input
    const compact = variant === 'compact'
    const { primaryAxis, rightAxis } = input
    const leftValues = primaryAxis?.values ?? values
    const axis = yAxisTicks(
        primaryAxis?.startAtZero ? [0, ...leftValues] : leftValues,
        primaryAxis?.kind ?? kind,
        compact ? COMPACT_Y_TICKS : undefined
    )
    const right = rightAxis
        ? yAxisTicks(
              rightAxis.startAtZero ? [0, ...rightAxis.values] : rightAxis.values,
              rightAxis.kind,
              compact ? COMPACT_Y_TICKS : undefined
          )
        : undefined
    // Mixed units need both scales even on a compact pin.
    const showYLabels = !compact || Boolean(rightAxis)
    const yTexts = showYLabels ? axis.ticks.map((tick) => (primaryAxis?.formatValue ?? formatValue)(tick)) : []
    const rightTexts = right?.ticks.map((tick) => (rightAxis?.formatValue ?? formatValue)(tick)) ?? []
    const rightYLabelWidth = Math.max(0, ...rightTexts.map((text) => monoTextWidth(text)))
    const yLabelWidth = Math.max(0, ...yTexts.map((text) => monoTextWidth(text)))
    const left = showYLabels ? yLabelWidth + TICK_GAP : 0
    const plot: PlotRect = {
        left,
        right: Math.max(left + 1, width - (rightAxis ? rightYLabelWidth + TICK_GAP : PLOT_RIGHT)),
        top: PLOT_TOP,
        bottom: Math.max(PLOT_TOP + 1, height - PLOT_BOTTOM),
    }
    const plotWidth = plot.right - plot.left

    // Bars sit in the middle of equal slots; a line runs from edge to edge.
    const bandWidth = plotWidth / Math.max(1, count)
    const xs: number[] = []
    for (let index = 0; index < count; index++) {
        if (kind === 'bar') {
            xs.push(plot.left + bandWidth * (index + 0.5))
        } else {
            xs.push(count === 1 ? plot.left + plotWidth / 2 : plot.left + (index / (count - 1)) * plotWidth)
        }
    }

    const yTicks = axis.ticks.map((value, index) => ({
        value,
        y: yPosition(value, axis.domain, plot),
        text: yTexts[index] ?? null,
    }))

    const texts = dates.map((at, index) => input.labels?.[index] ?? formatAxisDate(at, interval, input.uses24hourClock))
    const labelWidth = Math.max(0, ...texts.map((text) => monoTextWidth(text)))
    const indices = compact
        ? count > 1
            ? [0, count - 1]
            : count === 1
              ? [0]
              : []
        : xTickIndices(count, plotWidth, labelWidth)
    const xLabels = indices.map((index) => {
        const text = texts[index] ?? ''
        const textWidth = monoTextWidth(text) + X_LABEL_SLACK
        const center = xs[index] ?? plot.left
        let labelLeft = center - textWidth / 2
        if (compact) {
            // The two labels sit flush with the plot's edges, as on the web's small charts.
            labelLeft = index === 0 ? plot.left - X_LABEL_SLACK / 2 : plot.right - textWidth + X_LABEL_SLACK / 2
        }
        return { index, left: Math.min(width - textWidth, Math.max(0, labelLeft)), width: textWidth, text }
    })

    return {
        width,
        height,
        plot,
        xs,
        yDomain: axis.domain,
        yTicks,
        yLabelWidth,
        xLabels,
        bandWidth,
        ...(right
            ? {
                  rightYDomain: right.domain,
                  rightYLabelWidth,
                  rightYTicks: right.ticks.map((value, index) => ({
                      value,
                      y: yPosition(value, right.domain, plot),
                      text: rightTexts[index] ?? null,
                  })),
              }
            : {}),
    }
}
