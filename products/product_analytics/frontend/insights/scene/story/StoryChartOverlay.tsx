/* eslint-disable react/forbid-dom-props -- pixel positions from the chart's scales */
import { useActions, useValues } from 'kea'

import { useChartLayout } from '@posthog/quill-charts'

import { ChartDisplayType } from '~/types'
import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'

// The brand orange in both themes, so the highlight never reads as one of the chart's series.
const HIGHLIGHT_COLOR = 'var(--primary-light)'
const MARKER_SIZE = 20
const MARKER_GAP = 10
const FEATHER = 28
const MIN_REACH = 22
const BAR_PADDING = 4

interface Band {
    left: number
    right: number
}

// The chart runs its own hover and click on this layer, and a marker must not start them.
const BAR_DISPLAYS: (ChartDisplayType | null | undefined)[] = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsStackedBar,
]

const stopPropagation = (event: React.SyntheticEvent): void => event.stopPropagation()

export function StoryChartOverlay({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { storyOpen, chapters, highlightedChapter, storySeries, display } = useValues(insightStoryLogic(insightProps))
    const { setActiveMoment } = useActions(insightStoryLogic(insightProps))
    const { scales, dimensions, labels, series, resolvePositionValue } = useChartLayout()

    const chartSeries = storySeries ? series.find((candidate) => candidate.key === storySeries.key) : undefined
    if (!storyOpen || !chartSeries || !highlightedChapter) {
        return null
    }

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const xAt = (index: number): number | null => {
        const x = labels[index] == null ? undefined : scales.x(labels[index], chartSeries.key)
        return x == null || !isFinite(x) ? null : x
    }
    const first = xAt(0)
    const second = xAt(1)
    const step = first !== null && second !== null ? Math.abs(second - first) : plotWidth
    // A bar fills its slot. One stretch of a line needs its neighbours in view to read as a rise or a fall.
    const isBars = BAR_DISPLAYS.includes(display)
    const isOneStretch = highlightedChapter.moment.ranges.length === 1
    const reach = isBars
        ? step / 2 + (isOneStretch ? BAR_PADDING : 0)
        : isOneStretch
          ? Math.max(step, MIN_REACH)
          : step / 2

    const bands = highlightedChapter.moment.ranges
        .map(([start, end]): Band | null => {
            const from = xAt(start)
            const to = xAt(end)
            if (from === null || to === null) {
                return null
            }
            return {
                left: Math.max(Math.min(from, to) - reach, plotLeft),
                right: Math.min(Math.max(from, to) + reach, plotRight),
            }
        })
        .filter((band): band is Band => !!band && band.right > band.left)
        .sort((a, b) => a.left - b.left)

    const dims = bands.length
        ? [
              { left: plotLeft, right: bands[0].left, fadeLeft: false, fadeRight: true },
              ...bands.slice(1).map((band, index) => ({
                  left: bands[index].right,
                  right: band.left,
                  fadeLeft: true,
                  fadeRight: true,
              })),
              { left: bands[bands.length - 1].right, right: plotRight, fadeLeft: true, fadeRight: false },
          ]
        : []
    const tint = (share: number): string => `color-mix(in srgb, ${HIGHLIGHT_COLOR} ${share}%, transparent)`

    const yScale = (chartSeries.yAxisId && scales.yAxes?.[chartSeries.yAxisId]?.scale) || scales.y
    const placed: { x: number; top: number }[] = []
    const markers = chapters.flatMap((chapter, index) => {
        const anchor = chapter.moment.anchorIndex
        const x = anchor === null ? null : xAt(anchor)
        if (anchor === null || x === null) {
            return []
        }
        const y = yScale(resolvePositionValue(chartSeries, anchor))
        if (!isFinite(y) || x < plotLeft || x > plotRight) {
            return []
        }
        let top = Math.max(y - MARKER_SIZE - MARKER_GAP, plotTop)
        // Two moments on neighbouring points would put one marker on top of the other.
        while (placed.some((other) => Math.abs(other.x - x) < MARKER_SIZE && Math.abs(other.top - top) < MARKER_SIZE)) {
            top += MARKER_SIZE + 2
        }
        placed.push({ x, top })
        return [{ chapter, number: index + 1, x, y, top }]
    })

    return (
        <div data-attr="quill-insight-story-overlay">
            {dims.map((dim, index) => {
                const width = Math.max(dim.right - dim.left, 0)
                const feather = Math.min(FEATHER, width / 2)
                return (
                    <div
                        key={dims.length === 2 ? `dim-${index}` : `dim-${index}-of-${dims.length}`}
                        className="pointer-events-none absolute opacity-65 transition-[left,width] duration-500 ease-out starting:opacity-0"
                        style={{
                            left: dim.left,
                            top: plotTop,
                            width,
                            height: plotHeight,
                            background: `linear-gradient(to right, ${dim.fadeLeft ? 'transparent' : 'var(--card)'}, var(--card) ${feather}px, var(--card) calc(100% - ${feather}px), ${dim.fadeRight ? 'transparent' : 'var(--card)'})`,
                        }}
                    />
                )
            })}
            {bands.map((band, index) => (
                <div
                    key={bands.length === 1 ? 'band' : `band-${index}-of-${bands.length}`}
                    // Every lit stretch gets the top edge. Side lines on many of them would read as a barcode.
                    className={`pointer-events-none absolute rounded-t-md border-t-2 transition-[left,width,opacity] duration-500 ease-out starting:opacity-0 ${
                        bands.length === 1 ? 'border-x' : ''
                    }`}
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
            ))}
            {markers.map(({ chapter, number, x, y, top }) => {
                const active = chapter.moment.id === highlightedChapter.moment.id
                return (
                    <div key={chapter.moment.id}>
                        {active && (
                            <div
                                className="pointer-events-none absolute rounded-full border-2 bg-(--card)"
                                style={{
                                    left: x - 6,
                                    top: y - 6,
                                    width: 12,
                                    height: 12,
                                    borderColor: chartSeries.color,
                                    boxShadow: `0 0 0 4px ${tint(30)}`,
                                }}
                            />
                        )}
                        <button
                            type="button"
                            data-hog-charts-interactive-overlay
                            data-attr="quill-insight-story-marker"
                            aria-label={`Chapter ${number}: ${chapter.moment.title}`}
                            aria-current={active ? 'step' : undefined}
                            className={`pointer-events-auto absolute flex cursor-pointer items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors ${
                                active
                                    ? 'border-(--foreground) bg-(--foreground) text-(--background)'
                                    : 'border-(--border) bg-(--card) text-(--foreground) hover:border-(--foreground)'
                            }`}
                            style={{ left: x - MARKER_SIZE / 2, top, width: MARKER_SIZE, height: MARKER_SIZE }}
                            onClick={(event) => {
                                event.stopPropagation()
                                setActiveMoment(chapter.moment.id)
                            }}
                            onMouseDown={stopPropagation}
                            onMouseMove={stopPropagation}
                        >
                            {number}
                        </button>
                    </div>
                )
            })}
        </div>
    )
}
