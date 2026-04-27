import * as d3 from 'd3'

import type { SparklineData, SparklineDatum, SparklineEvent, VolumeSparklineXAxisMode } from './types'
import { renderVolumeSparklineEventMarkers } from './volumeSparklineEvents'

const VOLUME_SPARKLINE_X_AXIS_RESERVE_PX: Record<VolumeSparklineXAxisMode, number> = {
    full: 26,
    minimal: 2,
    none: 0,
}

const VOLUME_SPARKLINE_EVENT_LABEL_BAR_GAP_PX = 10

const STRIPE_CELL = 12

const DRAG_MIN_DISTANCE_PX = 5

export type VolumeSparklineRenderArgs = {
    data: SparklineData
    width: number
    height: number
    xAxis: VolumeSparklineXAxisMode
    backgroundColor: string
    hoverBackgroundColor: string
    axisColor: string
    borderRadius: number
    minBarHeight: number
    eventLabelHeight: number
    barWidthFraction?: number
    onHoverChange?: (index: number | null, datum: SparklineDatum | null) => void
    events?: SparklineEvent<string>[]
    onEventHoverChange?: (event: SparklineEvent<string> | null) => void
    eventLabelPaddingX?: number
    eventLabelPaddingY?: number
    eventMinSpace?: number
    onRangeSelect?: (startDate: Date, endDate: Date) => void
    onSpikeClick?: (datum: SparklineDatum, clientX: number, clientY: number) => void
    /** Used to namespace window-level d3 drag listeners so multiple sparklines do not clobber each other */
    sparklineKey: string
}

function roundedTopBarBottomClipPx(borderRadius: number): number {
    return borderRadius + 1
}

function roundedTopBarClipPathPx(borderRadius: number): string {
    return `inset(0 0 ${roundedTopBarBottomClipPx(borderRadius)}px 0)`
}

function hashColorId(color: string): string {
    let h = 0
    for (let i = 0; i < color.length; i++) {
        h = (h * 31 + color.charCodeAt(i)) | 0
    }
    return `spike-${(h >>> 0).toString(36)}`
}

function spikeBarFill(d: SparklineDatum, defaultColor: string, patternIdFor: (c: string) => string): string {
    if (d.animated && d.color) {
        return `url(#${patternIdFor(d.color)})`
    }
    return d.color || defaultColor
}

function createeStripePatterns(
    defs: d3.Selection<SVGDefsElement, unknown, null, undefined>,
    animatedColors: string[]
): (color: string) => string {
    const idByColor = new Map<string, string>()
    for (const color of animatedColors) {
        if (!idByColor.has(color)) {
            const id = hashColorId(color)
            idByColor.set(color, id)

            const pattern = defs
                .append('pattern')
                .attr('id', id)
                .attr('patternUnits', 'userSpaceOnUse')
                .attr('width', STRIPE_CELL)
                .attr('height', STRIPE_CELL)

            pattern.append('rect').attr('width', STRIPE_CELL).attr('height', STRIPE_CELL).attr('fill', color)

            pattern
                .append('path')
                .attr(
                    'd',
                    `M-1,1 l2,-2 M0,${STRIPE_CELL} l${STRIPE_CELL},-${STRIPE_CELL} M${STRIPE_CELL - 1},${STRIPE_CELL + 1} l2,-2`
                )
                .attr('stroke', 'rgba(255,255,255,0.4)')
                .attr('stroke-width', (STRIPE_CELL * Math.SQRT2) / 4)

            pattern
                .append('animateTransform')
                .attr('attributeName', 'patternTransform')
                .attr('type', 'translate')
                .attr('from', '0 0')
                .attr('to', `0 -${STRIPE_CELL}`)
                .attr('dur', '1.5s')
                .attr('repeatCount', 'indefinite')
        }
    }
    return (color: string) => idByColor.get(color) ?? hashColorId(color)
}

export function renderVolumeSparkline(svgEl: SVGSVGElement, args: VolumeSparklineRenderArgs): () => void {
    const {
        data,
        width,
        height,
        xAxis,
        backgroundColor,
        hoverBackgroundColor,
        axisColor,
        borderRadius,
        minBarHeight,
        eventLabelHeight,
        barWidthFraction = 0.9,
        onHoverChange,
        events = [],
        onEventHoverChange,
        eventLabelPaddingX = 5,
        eventLabelPaddingY = 3,
        eventMinSpace = 2,
        onRangeSelect,
        onSpikeClick,
        sparklineKey,
    } = args

    const svg = d3.select(svgEl)
    svg.selectAll('*').remove()

    if (width <= 0 || height <= 0 || data.length < 2) {
        return () => {}
    }

    let isDragging = false

    const gatedOnHoverChange = onHoverChange
        ? (index: number | null, datum: SparklineDatum | null): void => {
              if (isDragging) {
                  return
              }
              onHoverChange(index, datum)
          }
        : undefined

    const gatedOnEventHoverChange = onEventHoverChange
        ? (event: SparklineEvent<string> | null): void => {
              if (isDragging) {
                  return
              }
              onEventHoverChange(event)
          }
        : undefined

    const axisReserve = VOLUME_SPARKLINE_X_AXIS_RESERVE_PX[xAxis]
    const chartHeight = Math.max(1, height - axisReserve)

    const occurrences = data
    const timeDiff = Math.abs(occurrences[1].date.getTime() - occurrences[0].date.getTime())
    const extent = d3.extent(occurrences.map((d) => d.date)) as [Date, Date]
    const maxDate = new Date(extent[1])
    maxDate.setTime(extent[1].getTime() + timeDiff)

    const xScale = d3.scaleTime().domain([extent[0], maxDate]).range([0, width])

    const maxValue = d3.max(occurrences.map((d) => d.value)) || 0
    const barPlotTop =
        eventLabelHeight > 0 ? eventLabelHeight + VOLUME_SPARKLINE_EVENT_LABEL_BAR_GAP_PX : eventLabelHeight
    const yScale = d3
        .scaleLinear()
        .domain([0, maxValue || 1])
        .range([chartHeight - minBarHeight, barPlotTop])

    const animatedColors = [...new Set(occurrences.filter((d) => d.animated && d.color).map((d) => d.color as string))]

    const defs = svg.append('defs')
    const patternIdFor = createeStripePatterns(defs, animatedColors)

    const xTicks = d3.timeTicks(extent[0], maxDate, 8)
    const xAxisFull = d3.axisBottom(xScale).tickValues(xTicks).tickSize(0).tickPadding(5)

    const bandwidth = xScale(occurrences[1].date) - xScale(occurrences[0].date)

    const axisLineY = chartHeight
    const showAxisHover = xAxis === 'minimal' || xAxis === 'full'

    if (xAxis === 'minimal') {
        svg.append('line')
            .attr('class', 'volume-sparkline-x-axis-baseline')
            .attr('x1', 0)
            .attr('x2', width)
            .attr('y1', axisLineY)
            .attr('y2', axisLineY)
            .attr('stroke', 'currentColor')
            .attr('stroke-opacity', 0.22)
            .attr('pointer-events', 'none')
    }

    const barGroups = svg
        .selectAll<SVGGElement, SparklineDatum>('g.volume-bar')
        .data(occurrences)
        .join('g')
        .attr('class', 'volume-bar')
        .style('cursor', (d) => {
            if (onSpikeClick && d.animated) {
                return 'pointer'
            }
            return onRangeSelect ? 'crosshair' : 'default'
        })

    barGroups.each(function (d, i) {
        const g = d3.select(this)
        const binLeft = xScale(d.date)
        const barW = bandwidth * barWidthFraction
        const barX = binLeft + (bandwidth - barW) / 2

        const barTop = yScale(d.value)
        const barHeight = d.value > 0 ? chartHeight - yScale(d.value) : 0

        const fill = spikeBarFill(d, backgroundColor, patternIdFor)

        if (barHeight > 0) {
            const clip = roundedTopBarClipPathPx(borderRadius)
            const bottomClipPx = roundedTopBarBottomClipPx(borderRadius)
            const barRectHeight = chartHeight - barTop + bottomClipPx
            g.append('rect')
                .attr('class', 'bar-main')
                .attr('x', barX)
                .attr('y', barTop)
                .attr('width', barW)
                .attr('height', barRectHeight)
                .attr('rx', borderRadius)
                .attr('ry', borderRadius)
                .style('clip-path', clip)
                .style('fill', fill)

            g.append('rect')
                .attr('class', 'bar-hover-overlay')
                .attr('x', barX)
                .attr('y', barTop)
                .attr('width', barW)
                .attr('height', barRectHeight)
                .attr('rx', borderRadius)
                .attr('ry', borderRadius)
                .style('clip-path', clip)
                .style('fill', 'black')
                .style('opacity', 0)
                .style('pointer-events', 'none')
        }

        const maxDomain = Math.max(...yScale.domain())
        g.append('rect')
            .attr('class', 'bar-hit')
            .attr('x', binLeft)
            .attr('y', yScale(maxDomain))
            .attr('width', bandwidth)
            .attr('height', chartHeight - yScale(maxDomain))
            .style('fill', 'transparent')
            .style('pointer-events', 'all')

        g.on('mouseover', () => {
            gatedOnEventHoverChange?.(null)
            gatedOnHoverChange?.(i, d)
            if (showAxisHover) {
                const axis = svg.select('.volume-sparkline-x-axis-hover')
                if (d.value === 0) {
                    axis.attr('x1', barX)
                        .attr('x2', barX + barW)
                        .attr('stroke-opacity', 0.55)
                } else {
                    axis.attr('stroke-opacity', 0)
                }
            }
            if (isDragging) {
                return
            }
            if (d.animated && d.color) {
                g.select('.bar-hover-overlay').style('fill', 'white').style('opacity', 0.22)
            } else {
                g.select('.bar-main').style('fill', hoverBackgroundColor)
            }
        })

        g.on('mouseout', () => {
            if (isDragging) {
                return
            }
            g.select('.bar-hover-overlay').style('opacity', 0).style('fill', 'black')
            g.select('.bar-main').style('fill', spikeBarFill(d, backgroundColor, patternIdFor))
        })

        if (onSpikeClick && d.animated && !onRangeSelect) {
            g.on('click', (event: MouseEvent) => {
                event.stopPropagation()
                onSpikeClick(d, event.clientX, event.clientY)
            })
        }
    })

    if (xAxis === 'full') {
        svg.append('g').attr('transform', `translate(0,${chartHeight})`).style('color', axisColor).call(xAxisFull)
    }

    if (showAxisHover) {
        svg.append('line')
            .attr('class', 'volume-sparkline-x-axis-hover')
            .attr('x1', 0)
            .attr('x2', 0)
            .attr('y1', axisLineY)
            .attr('y2', axisLineY)
            .attr('stroke', 'currentColor')
            .attr('stroke-opacity', 0)
            .attr('stroke-width', 2.5)
            .attr('pointer-events', 'none')
    }

    if (events.length > 0) {
        renderVolumeSparklineEventMarkers(
            svg,
            events,
            xScale,
            chartHeight,
            width,
            {
                eventLabelHeight,
                eventLabelPaddingX,
                eventLabelPaddingY,
                eventMinSpace,
                borderRadius,
            },
            gatedOnHoverChange,
            gatedOnEventHoverChange
        )
    }

    // Hover cursor line (vertical indicator) – only for range-selectable charts
    let hoverCursorLine: d3.Selection<SVGLineElement, unknown, null, undefined> | null = null
    if (onRangeSelect) {
        hoverCursorLine = svg
            .append('line')
            .attr('class', 'volume-sparkline-hover-cursor')
            .attr('y1', barPlotTop)
            .attr('y2', chartHeight)
            .attr('stroke', 'rgba(128, 128, 128, 0.5)')
            .attr('stroke-width', 1)
            .attr('pointer-events', 'none')
            .style('opacity', 0)

        svg.on('mousemove.cursor', (event: MouseEvent) => {
            if (isDragging) {
                return
            }
            const [mx] = d3.pointer(event)
            hoverCursorLine!.attr('x1', mx).attr('x2', mx).style('opacity', 1)
        })
    }

    svg.on('mouseleave', () => {
        if (isDragging) {
            return
        }
        hoverCursorLine?.style('opacity', 0)
        gatedOnEventHoverChange?.(null)
        gatedOnHoverChange?.(null, null)
        if (showAxisHover) {
            svg.select('.volume-sparkline-x-axis-hover').attr('stroke-opacity', 0)
        }
        svg.selectAll<SVGGElement, SparklineDatum>('g.volume-bar').each(function (d) {
            const g = d3.select(this)
            g.select('.bar-hover-overlay').style('opacity', 0).style('fill', 'black')
            g.select('.bar-main').style('fill', spikeBarFill(d, backgroundColor, patternIdFor))
        })
    })

    // Drag-to-select range
    if (onRangeSelect) {
        let dragStartX = -1

        const selectionOverlay = svg
            .append('rect')
            .attr('class', 'drag-selection-overlay')
            .attr('y', barPlotTop)
            .attr('height', chartHeight - barPlotTop)
            .attr('rx', 0)
            .attr('ry', 0)
            .style('fill', 'rgba(128, 128, 128, 0.15)')
            .style('stroke', 'none')
            .style('pointer-events', 'none')
            .style('opacity', 0)

        function resetBarStyles(): void {
            barGroups.each(function (d: SparklineDatum) {
                const g = d3.select(this)
                g.select('.bar-main')
                    .style('fill', spikeBarFill(d, backgroundColor, patternIdFor))
                    .style('opacity', null)
                g.select('.bar-hover-overlay').style('opacity', 0).style('fill', 'black')
            })
        }

        svg.on('mousedown', (event: MouseEvent) => {
            if (event.button !== 0) {
                return
            }
            event.preventDefault()

            const [mx] = d3.pointer(event)
            dragStartX = mx

            onHoverChange?.(null, null)
            onEventHoverChange?.(null)

            isDragging = true

            svg.style('cursor', 'col-resize')
            hoverCursorLine?.style('opacity', 0)
        })

        const handleMouseMove = (event: MouseEvent): void => {
            if (!isDragging) {
                return
            }

            const [mx] = d3.pointer(event, svgEl)
            const clampedX = Math.max(0, Math.min(mx, width))
            const left = Math.min(dragStartX, clampedX)
            const right = Math.max(dragStartX, clampedX)

            selectionOverlay
                .attr('x', left)
                .attr('width', Math.max(0, right - left))
                .style('opacity', 1)

            for (let i = 0; i < occurrences.length; i++) {
                const binLeft = xScale(occurrences[i].date)
                if (clampedX >= binLeft && clampedX < binLeft + bandwidth) {
                    onHoverChange?.(i, occurrences[i])
                    break
                }
            }

            // Highlight bars inside selection, dim bars outside
            barGroups.each(function (d: SparklineDatum) {
                const g = d3.select(this)
                const binLeft = xScale(d.date)
                const binCenter = binLeft + bandwidth / 2
                const inSelection = binCenter >= left && binCenter <= right

                if (inSelection) {
                    g.select('.bar-main').style('opacity', null)
                    if (d.animated && d.color) {
                        g.select('.bar-hover-overlay').style('fill', 'white').style('opacity', 0.15)
                    } else {
                        g.select('.bar-main').style('fill', hoverBackgroundColor)
                    }
                } else {
                    g.select('.bar-main')
                        .style('fill', spikeBarFill(d, backgroundColor, patternIdFor))
                        .style('opacity', 0.3)
                    g.select('.bar-hover-overlay').style('opacity', 0)
                }
            })
        }

        const handleMouseUp = (event: MouseEvent): void => {
            if (!isDragging) {
                return
            }
            isDragging = false

            svg.style('cursor', 'crosshair')

            const [mx] = d3.pointer(event, svgEl)
            const clampedX = Math.max(0, Math.min(mx, width))
            const dragDist = Math.abs(clampedX - dragStartX)

            selectionOverlay.style('opacity', 0)

            resetBarStyles()

            if (dragDist < DRAG_MIN_DISTANCE_PX) {
                if (onSpikeClick) {
                    for (let i = 0; i < occurrences.length; i++) {
                        const binLeft = xScale(occurrences[i].date)
                        if (clampedX >= binLeft && clampedX < binLeft + bandwidth) {
                            if (occurrences[i].animated) {
                                onSpikeClick(occurrences[i], event.clientX, event.clientY)
                            }
                            break
                        }
                    }
                }
                return
            }

            const left = Math.min(dragStartX, clampedX)
            const right = Math.max(dragStartX, clampedX)

            let startDate: Date | null = null
            let endDate: Date | null = null

            for (const d of occurrences) {
                const binLeft = xScale(d.date)
                const binCenter = binLeft + bandwidth / 2
                if (binCenter >= left && binCenter <= right) {
                    if (!startDate || d.date < startDate) {
                        startDate = d.date
                    }
                    if (!endDate || d.date > endDate) {
                        endDate = d.date
                    }
                }
            }

            if (startDate && endDate) {
                onRangeSelect(startDate, new Date(endDate.getTime() + timeDiff))
            }
        }

        const namespace = `sparkline-drag-${sparklineKey}`
        d3.select(window as EventTarget as Window).on(`mousemove.${namespace}`, handleMouseMove)
        d3.select(window as EventTarget as Window).on(`mouseup.${namespace}`, handleMouseUp)

        return () => {
            d3.select(window as EventTarget as Window).on(`mousemove.${namespace}`, null)
            d3.select(window as EventTarget as Window).on(`mouseup.${namespace}`, null)
            svg.on('mousemove.cursor', null)
        }
    }

    return () => {
        svg.on('mousemove.cursor', null)
    }
}
