import * as d3 from 'd3'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import { DateRange } from '~/queries/schema/schema-general'

import { BUBBLE_UP_BUTTON_TOOLTIP } from './bubbleUpCopy'
import { formatDuration } from './TraceFlameChart'
import type { HeatmapCellRow } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import type { TracingHeatmapYScale } from './tracingFiltersLogic'
import { tracingSceneLogic } from './tracingSceneLogic'

const MARGIN = { top: 8, right: 12, bottom: 28, left: 72 }

function bucketToNanoRange(bucket: number): { min: number; maxExclusive: number } {
    const lo = Math.pow(2, bucket)
    const hi = Math.pow(2, bucket + 1)
    return { min: lo, maxExclusive: hi }
}

function indexFromBandPx(px: number, scale: d3.ScaleBand<string>, keys: string[]): number {
    for (let i = 0; i < keys.length; i++) {
        const p = scale(keys[i])
        if (p !== undefined && px >= p - 0.5 && px <= p + scale.bandwidth() + 0.5) {
            return i
        }
    }
    const step = scale.step()
    const idx = Math.floor((px - (scale(keys[0]) ?? 0) + scale.padding() * step) / step)
    return Math.max(0, Math.min(keys.length - 1, idx))
}

interface TracingLatencyHeatmapProps {
    rows: HeatmapCellRow[]
    loading: boolean
    yScaleMode: TracingHeatmapYScale
    utcDateRange: DateRange
    displayTimezone: string
}

export function TracingLatencyHeatmap({
    rows,
    loading,
    yScaleMode,
    utcDateRange,
    displayTimezone,
}: TracingLatencyHeatmapProps): JSX.Element {
    const { selectedRegion } = useValues(tracingFiltersLogic)
    const { setSelectedRegion, clearSelectedRegion } = useActions(tracingFiltersLogic)
    const { applyZoomFromSelectedRegion, runBubbleUp } = useActions(tracingSceneLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const svgRef = useRef<SVGSVGElement>(null)
    const [size, setSize] = useState({ width: 640, height: 220 })

    useEffect(() => {
        const el = containerRef.current
        if (!el) {
            return
        }
        const ro = new ResizeObserver((entries) => {
            const cr = entries[0]?.contentRect
            if (cr && cr.width > 0) {
                setSize({ width: Math.floor(cr.width), height: 220 })
            }
        })
        ro.observe(el)
        return () => ro.disconnect()
    }, [])

    const { times, buckets, cellMap, maxCount } = useMemo(() => {
        const tset = new Set<string>()
        const bset = new Set<number>()
        const cmap = new Map<string, { count: number; topService: string; topCount: number }>()

        for (const r of rows) {
            tset.add(r.time)
            bset.add(r.duration_log2_bucket)
            const key = `${r.time}\t${r.duration_log2_bucket}`
            const prev = cmap.get(key) ?? { count: 0, topService: '', topCount: 0 }
            const nextCount = prev.count + r.count
            let topService = prev.topService
            let topCount = prev.topCount
            if (r.count >= topCount) {
                topService = r.service || topService
                topCount = r.count
            }
            cmap.set(key, { count: nextCount, topService, topCount })
        }

        const times = [...tset].sort((a, b) => dayjs(a).valueOf() - dayjs(b).valueOf())
        const bucketsRaw = [...bset].sort((a, b) => a - b)
        const buckets = yScaleMode === 'log' ? [...bucketsRaw].reverse() : bucketsRaw
        let maxC = 0
        for (const v of cmap.values()) {
            maxC = Math.max(maxC, v.count)
        }
        return { times, buckets, cellMap: cmap, maxCount: maxC }
    }, [rows, yScaleMode])

    const innerW = Math.max(1, size.width - MARGIN.left - MARGIN.right)
    const innerH = Math.max(1, size.height - MARGIN.top - MARGIN.bottom)

    const x = useMemo(() => {
        return d3.scaleBand().domain(times).range([0, innerW]).paddingInner(0.05).paddingOuter(0)
    }, [times, innerW])

    const yBand = useMemo(() => {
        return d3.scaleBand().domain(buckets.map(String)).range([innerH, 0]).paddingInner(0.08)
    }, [buckets, innerH])

    const color = useMemo(() => {
        const dom: [number, number] = [1, Math.max(2, maxCount)]
        return d3.scaleSequentialLog(d3.interpolateViridis).domain(dom)
    }, [maxCount])

    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const flushRegion = useCallback(
        (sel: [[number, number], [number, number]] | null) => {
            if (!sel || times.length === 0 || buckets.length === 0) {
                return
            }
            const [[rx0, ry0], [rx1, ry1]] = sel
            const px0 = Math.max(0, Math.min(innerW, Math.min(rx0, rx1)))
            const px1 = Math.max(0, Math.min(innerW, Math.max(rx0, rx1)))
            const py0 = Math.max(0, Math.min(innerH, Math.min(ry0, ry1)))
            const py1 = Math.max(0, Math.min(innerH, Math.max(ry0, ry1)))

            const timeKeys = times
            const xiLo = indexFromBandPx(px0, x, timeKeys)
            const xiHi = indexFromBandPx(px1, x, timeKeys)
            const iLo = Math.min(xiLo, xiHi)
            const iHi = Math.max(xiLo, xiHi)
            const timeFrom = times[iLo]
            const timeTo =
                iHi + 1 < times.length ? times[iHi + 1] : (utcDateRange.date_to ?? dayjs().utc().toISOString())

            const bucketKeys = buckets.map(String)
            const yiLo = indexFromBandPx(py0, yBand, bucketKeys)
            const yiHi = indexFromBandPx(py1, yBand, bucketKeys)
            const bLo = Math.min(buckets[yiLo] ?? buckets[0], buckets[yiHi] ?? buckets[0])
            const bHi = Math.max(buckets[yiLo] ?? buckets[0], buckets[yiHi] ?? buckets[0])

            const { min: dMin } = bucketToNanoRange(bLo)
            const { maxExclusive: dMax } = bucketToNanoRange(bHi)

            setSelectedRegion({
                time_from: timeFrom,
                time_to: timeTo,
                duration_min_nano: Math.floor(dMin),
                duration_max_nano: Math.ceil(dMax),
            })
        },
        [buckets, innerH, innerW, setSelectedRegion, times, utcDateRange.date_to, x, yBand]
    )

    useEffect(() => {
        const svgEl = svgRef.current
        if (!svgEl || times.length === 0 || buckets.length === 0) {
            return
        }

        const svg = d3.select(svgEl)
        svg.selectAll('*').remove()

        const g = svg
            .attr('width', size.width)
            .attr('height', size.height)
            .append('g')
            .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

        const xAxis = d3.axisBottom(x).tickFormat((d) => {
            const v = String(d)
            const dt = displayTimezone ? dayjs(v).tz(displayTimezone) : dayjs(v)
            return dt.format(times.length > 48 ? 'HH:mm' : 'HH:mm:ss')
        })
        g.append('g')
            .attr('transform', `translate(0,${innerH})`)
            .call(xAxis)
            .selectAll('text')
            .attr('font-size', 10)
            .attr('transform', 'rotate(-35)')
            .style('text-anchor', 'end')

        const axis = d3.axisLeft(yBand).tickFormat((d) => {
            const b = Number(d)
            const { min } = bucketToNanoRange(b)
            return formatDuration(min)
        })
        g.append('g').call(axis).selectAll('text').attr('font-size', 10)

        for (const t of times) {
            for (const b of buckets) {
                const key = `${t}\t${b}`
                const cell = cellMap.get(key)
                const c = cell?.count ?? 0
                if (c <= 0) {
                    continue
                }
                const x0 = x(t)
                const bw = x.bandwidth()
                const y0 = yBand(String(b)) ?? 0
                const bh = yBand.bandwidth()
                g.append('rect')
                    .attr('x', x0)
                    .attr('y', y0)
                    .attr('width', bw)
                    .attr('height', bh)
                    .attr('rx', 2)
                    .attr('fill', color(c))
                    .attr('stroke', 'var(--border-primary)')
                    .attr('stroke-width', 0.5)
                    .append('title')
                    .text(
                        `${t}\n${formatDuration(bucketToNanoRange(b).min)} – ${formatDuration(bucketToNanoRange(b).maxExclusive)}\ncount: ${c}${cell?.topService ? `\nTop service: ${cell.topService}` : ''}`
                    )
            }
        }

        const brush = d3
            .brush()
            .extent([
                [0, 0],
                [innerW, innerH],
            ])
            .on('end', (event) => {
                if (!event.selection) {
                    return
                }
                const sel = event.selection as [[number, number], [number, number]]
                if (debounceRef.current) {
                    clearTimeout(debounceRef.current)
                }
                debounceRef.current = setTimeout(() => flushRegion(sel), 200)
            })

        g.append('g').attr('class', 'brush').call(brush)

        return () => {
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
            }
        }
    }, [
        buckets,
        cellMap,
        color,
        displayTimezone,
        flushRegion,
        innerH,
        innerW,
        size.height,
        size.width,
        times,
        x,
        yBand,
    ])

    const empty = !loading && rows.length === 0

    return (
        <div ref={containerRef} className="relative flex flex-col gap-2 w-full">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 rounded-md bg-bg-mid/80 px-2 py-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        disabled={!selectedRegion}
                        onClick={() => selectedRegion && applyZoomFromSelectedRegion(selectedRegion)}
                    >
                        Zoom to selection
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        disabled={!selectedRegion}
                        onClick={() => selectedRegion && runBubbleUp(selectedRegion)}
                        tooltip={BUBBLE_UP_BUTTON_TOOLTIP}
                    >
                        BubbleUp
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        disabled={!selectedRegion}
                        icon={<IconTrash />}
                        onClick={() => clearSelectedRegion()}
                    >
                        Clear
                    </LemonButton>
                </div>
                {selectedRegion ? (
                    <span className="text-xs text-muted font-mono tabular-nums border-l border-primary pl-2 ml-0.5">
                        {dayjs(selectedRegion.time_from).format('HH:mm:ss')} —{' '}
                        {dayjs(selectedRegion.time_to).format('HH:mm:ss')} ·{' '}
                        {formatDuration(selectedRegion.duration_min_nano)} –{' '}
                        {formatDuration(selectedRegion.duration_max_nano)}
                    </span>
                ) : (
                    <span className="text-xs text-muted border-l border-transparent pl-2">
                        Brush the chart to select time and duration
                    </span>
                )}
            </div>
            <div
                className={cn('relative rounded border border-primary overflow-hidden bg-bg-mid', empty && 'min-h-32')}
            >
                {empty ? (
                    <div className="h-32 flex items-center justify-center text-muted text-sm">
                        No spans match — try widening the time range or filters
                    </div>
                ) : (
                    <svg ref={svgRef} className="block w-full" role="img" aria-label="Latency heatmap" />
                )}
                {loading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
