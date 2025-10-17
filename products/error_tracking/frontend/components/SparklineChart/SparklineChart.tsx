import * as d3 from 'd3'
import { useEffect, useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

import { cn } from 'lib/utils/css-classes'

export type SparklineDatum = {
    date: Date
    value: number
    label?: string
}

export type SparklineEvent<T> = {
    id: string
    date: Date
    payload: T
    radius?: number
    color?: string
}

export type SparklineData = SparklineDatum[]

export type SparklineProps = {
    data: SparklineData
    events?: SparklineEvent<string>[]
    options: SparklineOptions
    className?: string
}

export type SparklineOptions = {
    onDatumMouseEnter?: (data: SparklineDatum) => void
    onDatumMouseLeave?: (data: SparklineDatum) => void
    onEventMouseEnter?: (evt: SparklineEvent<string>) => void
    onEventMouseLeave?: (evt: SparklineEvent<string>) => void
    onEventClick?: (evt: SparklineEvent<string>) => void
    backgroundColor: string
    hoverBackgroundColor: string
    axisColor: string
    borderRadius: number
    eventLabelHeight: number // Control the chart height reserved to event labels
    eventMinSpace: number // Control the spacing between events when they collapse
    eventLabelPaddingX: number //Control the padding on the rect label
    eventLabelPaddingY: number
    minBarHeight: number // Minimum height of a bar in the sparkline chart (in pixels)
}

export function SparklineChart({ data, events = [], options, className }: SparklineProps): JSX.Element {
    const svgRef = useRef<SVGSVGElement>(null)
    const { height: contentHeight, width: contentWidth, ref: contentRef } = useResizeObserver({ box: 'content-box' })

    useEffect(() => {
        const svgEl = svgRef.current
        if (svgEl && contentHeight && contentWidth) {
            const svg = d3.select(svgEl)
            const occurrences = data
            if (occurrences.length < 2) {
                throw new Error('Not enough data to render chart')
            }
            const timeDiff = Math.abs(occurrences[1].date.getTime() - occurrences[0].date.getTime())
            const extent = d3.extent(occurrences.map((d) => d.date)) as [Date, Date]
            const maxDate = new Date(extent[1])
            maxDate.setTime(extent[1].getTime() + timeDiff)
            const xTicks = d3.timeTicks(extent[0], maxDate, 8)
            const xScale = d3.scaleTime().domain([extent[0], maxDate]).range([0, contentWidth])

            const maxValue = d3.max(occurrences.map((d) => d.value)) || 0
            const yScale = d3
                .scaleLinear()
                .domain([0, maxValue || 1])
                .range([contentHeight - options.minBarHeight, options.eventLabelHeight])

            const xAxis = d3.axisBottom(xScale).tickValues(xTicks).tickSize(0).tickPadding(5)

            svg.selectAll('g.datum')
                .data(occurrences)
                .enter()
                .append('g')
                .attr('class', 'datum')
                .call(buildBarGroup, xScale, yScale, contentHeight, occurrences, options)

            svg.append('g')
                .attr('transform', `translate(0,${contentHeight})`)
                .style('color', options.axisColor)
                .call(xAxis)

            svg.selectAll('g.event')
                .data(events || [])
                .enter()
                .append('g')
                .attr('class', 'event')
                .call(buildEvent, xScale, options, contentHeight, contentWidth)

            return () => {
                // Remove event listeners
                svg.selectAll('*').remove()
            }
        }
    }, [data, events, options, contentHeight, contentWidth])

    return (
        <div ref={contentRef} className={cn('h-full w-full p-4 overflow-hidden', className)}>
            <svg ref={svgRef} className="overflow-visible" height="100%" width="100%" />
        </div>
    )
}

function buildBarGroup(
    group: d3.Selection<SVGGElement, SparklineDatum, SVGGElement, SparklineDatum>,
    xScale: d3.ScaleTime<number, number>,
    yScale: d3.ScaleLinear<number, number>,
    contentHeight: number,
    data: SparklineData,
    options: SparklineOptions
): void {
    const bandwidth = xScale(data[1].date) - xScale(data[0].date)
    group
        .attr('x', (d) => xScale(d.date))
        .on('mouseover', function (this, _, d: unknown) {
            const current = d3.select(this)
            options.onDatumMouseEnter?.(d as SparklineDatum)
            options.hoverBackgroundColor && current.select('.bar').style('fill', options.hoverBackgroundColor)
        })
        .on('mouseout', function (this, _, d: unknown) {
            const current = d3.select(this)
            options.onDatumMouseLeave?.(d as SparklineDatum)
            current.select('.bar').style('fill', options.backgroundColor)
        })

    group
        .append('rect')
        .attr('class', 'bar')
        .attr('x', (_, i) => xScale(data[i].date))
        .attr('y', (d) => yScale(d.value) + options.borderRadius)
        .attr('width', bandwidth * 0.9)
        .attr('height', (d) => (d && d.value > 0 ? contentHeight - yScale(d.value) : 0))
        .style('fill', options.backgroundColor)
        .style('clip-path', `inset(0 0 ${options.borderRadius + 1}px 0)`) // Offset by 1px to avoid overlapping on x axis
        .attr('rx', options.borderRadius)
        .attr('ry', options.borderRadius)

    const maxValue = Math.max(...yScale.domain())

    group
        .append('rect')
        .attr('class', 'overlay')
        .attr('x', (_, i) => xScale(data[i].date))
        .attr('y', yScale(maxValue))
        .attr('width', bandwidth)
        .attr('height', (d) => (d ? contentHeight - yScale(maxValue) + options.borderRadius : 0))
        .style('fill', 'transparent')
}

function buildEventLabel(
    selection: d3.Selection<SVGGElement, SparklineEvent<string>, SVGGElement, SparklineEvent<string>>,
    xScale: d3.ScaleTime<number, number>,
    options: SparklineOptions,
    contentWidth: number
): void {
    const paddingX = options.eventLabelPaddingX
    const paddingY = options.eventLabelPaddingY
    const baseLine = options.eventLabelHeight / 2

    const text = selection
        .append('text')
        .attr('class', 'font-semibold')
        .attr('x', (d) => xScale(d.date))
        .attr('y', baseLine)
        .attr('fill', 'white')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'central')
        .style('font-size', '10px')
        .text((d) => {
            return d.payload
        })

    const textNodes = text.nodes()

    selection
        .insert('rect', 'text')
        .attr('x', (_, i) => textNodes[i].getBBox().x - paddingX)
        .attr('y', (_, i) => textNodes[i].getBBox().y - paddingY)
        .attr('width', (_, i) => textNodes[i].getBBox().width + paddingX * 2)
        .attr('height', (_, i) => textNodes[i].getBBox().height + paddingY * 2)
        .attr('rx', options.borderRadius)
        .attr('ry', options.borderRadius)
        .attr('fill', (d) => d.color || 'black')

    const movingNodes = selection.nodes().map((node, index) => {
        const bbox = node.getBBox()
        const center = { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 }
        return { ...center, radius: bbox.width / 2 + options.eventMinSpace, id: `moving-${index}` }
    })

    const clonedNodes = movingNodes.map((node) => ({ ...node }))
    const simulation = d3
        .forceSimulation(movingNodes)
        .velocityDecay(0.9)
        .force(
            'collision',
            d3.forceCollide().radius((_, i) => movingNodes[i].radius)
        )
        .force('boundaries', forceBoundaries(movingNodes, -10, contentWidth + 10))

    simulation.stop()
    simulation.tick(500)
    movingNodes.forEach((_, index) => {
        const newX = movingNodes[index].x
        const initialX = clonedNodes[index].x
        const newY = movingNodes[index].y
        const initialY = clonedNodes[index].y
        const deltaX = newX - initialX
        const deltaY = newY - initialY
        selection
            .filter((_, i) => i === index)
            .attr('transform', `translate(${deltaX}, ${deltaY})`)
            .attr('dx', deltaX)
            .attr('dy', deltaY)
    })
}

function buildEventAnchor(
    selection: d3.Selection<SVGGElement, SparklineEvent<string>, SVGGElement, SparklineEvent<string>>,
    xScale: d3.ScaleTime<number, number>,
    contentHeight: number
): void {
    selection
        .append('circle')
        .attr('cx', (d) => xScale(d.date))
        .attr('cy', contentHeight)
        .attr('r', 6)
        .attr('fill', 'white')
        .attr('stroke', (d) => d.color || 'black')
        .attr('stroke-width', 2)
}

function buildEvent(
    selection: d3.Selection<SVGGElement, SparklineEvent<string>, SVGGElement, SparklineEvent<string>>,
    xScale: d3.ScaleTime<number, number>,
    options: SparklineOptions,
    contentHeight: number,
    contentWidth: number
): void {
    selection.append('g').attr('class', 'label').call(buildEventLabel, xScale, options, contentWidth)
    selection.call(buildEventLine, xScale, contentHeight, contentWidth)
    selection.call(buildEventAnchor, xScale, contentHeight)

    selection
        .style('cursor', options.onEventClick ? 'pointer' : 'default')
        .on('mouseover', function (this, _, d) {
            options.onEventMouseEnter?.(d)
        })
        .on('mouseout', function (this, _, d) {
            options.onEventMouseLeave?.(d)
        })
}

function buildEventLine(
    selection: d3.Selection<SVGGElement, SparklineEvent<string>, SVGGElement, SparklineEvent<string>>,
    xScale: d3.ScaleTime<number, number>,
    contentHeight: number,
    contentWidth: number
): void {
    selection
        .insert('line', 'g.label')
        .attr('x1', (d) => xScale(d.date))
        .attr('y1', contentHeight)
        .attr('x2', (_, index) => {
            const labelNode = selection
                .selectAll('.label')
                .nodes()
                .find((_, i) => i === index) as SVGGElement
            const dx = parseFloat(labelNode.getAttribute('dx') || '0')
            const labelBbox = labelNode.getBBox()
            return labelBbox?.x + dx + labelBbox?.width / 2 || 0
        })
        .attr('y2', 5)
        .attr('stroke-width', 2)
        .attr('stroke', (d) => {
            const xPos = xScale(d.date)
            if (xPos < 0 || xPos > contentWidth) {
                return 'transparent'
            }
            return d.color || 'black'
        })
}

function forceBoundaries(nodes: any, minX: number, maxX: number) {
    return () => {
        nodes.forEach((node: any) => {
            node.vy = 0
            if (node.x + node.radius > maxX) {
                node.vx += maxX - (node.x + node.radius)
            } else if (node.x - node.radius < minX) {
                node.vx += minX - (node.x - node.radius)
            }
        })
    }
}
