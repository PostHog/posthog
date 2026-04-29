import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from './types'
import type { Span } from './types'

interface TraceFlameChartProps {
    spans: Span[]
}

interface SpanNode {
    span: Span
    children: SpanNode[]
    depth: number
    isLastChild: boolean
    connectorLines: boolean[]
}

function buildSpanTree(spans: Span[]): SpanNode[] {
    const byId = new Map<string, SpanNode>()
    const roots: SpanNode[] = []

    for (const span of spans) {
        byId.set(span.span_id, { span, children: [], depth: 0, isLastChild: false, connectorLines: [] })
    }

    for (const node of byId.values()) {
        if (node.span.parent_span_id && byId.has(node.span.parent_span_id)) {
            const parent = byId.get(node.span.parent_span_id)!
            parent.children.push(node)
        } else {
            roots.push(node)
        }
    }

    function setDepths(nodes: SpanNode[], depth: number, parentConnectors: boolean[]): void {
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i]
            node.depth = depth
            node.isLastChild = i === nodes.length - 1
            node.connectorLines = [...parentConnectors]
            node.children.sort((a, b) => new Date(a.span.timestamp).getTime() - new Date(b.span.timestamp).getTime())
            setDepths(node.children, depth + 1, [...parentConnectors, !node.isLastChild])
        }
    }
    setDepths(roots, 0, [])

    return roots
}

function sortChildren(nodes: SpanNode[]): SpanNode[] {
    return [...nodes].sort((a, b) => parseTimestampUs(a.span.timestamp) - parseTimestampUs(b.span.timestamp))
}

function flattenTree(nodes: SpanNode[]): SpanNode[] {
    const result: SpanNode[] = []
    function walk(node: SpanNode): void {
        result.push(node)
        for (const child of sortChildren(node.children)) {
            walk(child)
        }
    }
    for (const root of sortChildren(nodes)) {
        walk(root)
    }
    return result
}

export function formatDuration(durationNano: number): string {
    const us = durationNano / 1_000
    if (us < 100) {
        return `${us.toFixed(1)}\u00B5s`
    }
    const ms = us / 1_000
    if (ms < 1000) {
        return `${ms.toFixed(ms < 10 ? 2 : 1)}ms`
    }
    return `${(ms / 1000).toFixed(2)}s`
}

/**
 * Parse an ISO 8601 timestamp string to microseconds since epoch.
 * `Date.getTime()` only gives millisecond resolution, losing sub-ms
 * precision from timestamps like "2024-01-15T10:30:00.123456Z".
 */
function parseTimestampUs(iso: string): number {
    const ms = new Date(iso).getTime()
    // Extract fractional seconds beyond milliseconds
    const dot = iso.indexOf('.')
    if (dot === -1) {
        return ms * 1_000
    }
    // Find the end of fractional digits (before 'Z')
    const fracEnd = iso.search(/[Z+-](\d\d:\d\d)?$/i)
    if (fracEnd === -1) {
        return ms * 1_000
    }
    const fracStr = iso.slice(dot + 1, fracEnd)
    // Pad or truncate to 6 digits (microseconds)
    const padded = fracStr.padEnd(6, '0').slice(0, 6)
    const totalUs = parseInt(padded, 10)
    // ms already includes the first 3 fractional digits, so add the remaining sub-ms part
    const subMsUs = totalUs % 1_000
    return ms * 1_000 + subMsUs
}

function buildServiceColorMap(spans: Span[]): Map<string, number> {
    const services = [...new Set(spans.map((s) => s.service_name))].sort()
    const map = new Map<string, number>()
    services.forEach((service, i) => map.set(service, i))
    return map
}

/** Generate evenly spaced tick marks for the timeline (in microseconds) */
function getTimelineTicks(durationUs: number): number[] {
    if (durationUs <= 0) {
        return []
    }
    const targetTickCount = 5
    const rawInterval = durationUs / targetTickCount
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawInterval)))
    const niceIntervals = [1, 2, 5, 10]
    const interval = niceIntervals.find((n) => n * magnitude >= rawInterval)! * magnitude
    const ticks: number[] = []
    for (let t = interval; t < durationUs; t += interval) {
        ticks.push(t)
    }
    return ticks
}

const INDENT_PX = 16
const DEFAULT_LABEL_COLUMN_WIDTH = 280
const MIN_LABEL_COLUMN_WIDTH = 120
const MAX_LABEL_COLUMN_WIDTH = 800
const LABEL_COLUMN_WIDTH_STORAGE_KEY = 'tracing-trace-label-width'
/** Hit area for the vertical splitter (centered on the label/timeline border). */
const LABEL_SPLITTER_HIT_PX = 8
const ROW_HEIGHT = 32

function clampLabelColumnWidth(px: number): number {
    return Math.min(MAX_LABEL_COLUMN_WIDTH, Math.max(MIN_LABEL_COLUMN_WIDTH, Math.round(px)))
}

function readStoredLabelColumnWidth(): number | null {
    if (typeof window === 'undefined') {
        return null
    }
    try {
        const raw = window.localStorage.getItem(LABEL_COLUMN_WIDTH_STORAGE_KEY)
        if (raw == null) {
            return null
        }
        const n = Number.parseInt(raw, 10)
        if (!Number.isFinite(n)) {
            return null
        }
        return clampLabelColumnWidth(n)
    } catch {
        return null
    }
}
const ERROR_COLOR = 'var(--danger)'

const TREE_LINE_W = 2
const TREE_COLOR = 'var(--border-bold)'
// Extend vertical lines well beyond row edges to eliminate subpixel gaps between siblings
const TREE_OVERFLOW = 2

function TreeIndent({ node }: { node: SpanNode }): JSX.Element | null {
    if (node.depth === 0) {
        return null
    }

    const mid = INDENT_PX / 2

    return (
        <span className="flex shrink-0 items-stretch self-stretch overflow-visible">
            {/* Continuation lines for ancestor levels */}
            {node.connectorLines.slice(0, -1).map((hasContinuation, i) => (
                <span
                    key={i}
                    className="shrink-0 relative overflow-visible"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: INDENT_PX }}
                >
                    {hasContinuation && (
                        <span
                            className="absolute"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                left: mid - TREE_LINE_W / 2,
                                top: -TREE_OVERFLOW,
                                bottom: -TREE_OVERFLOW,
                                width: TREE_LINE_W,
                                backgroundColor: TREE_COLOR,
                            }}
                        />
                    )}
                </span>
            ))}
            {/* Branch connector */}
            <span
                className="shrink-0 relative overflow-visible"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: INDENT_PX }}
            >
                {/* Vertical line — full height for middle children, stops at center for last child */}
                <span
                    className="absolute"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: mid - TREE_LINE_W / 2,
                        top: -TREE_OVERFLOW,
                        bottom: node.isLastChild ? '50%' : -TREE_OVERFLOW,
                        width: TREE_LINE_W,
                        backgroundColor: TREE_COLOR,
                    }}
                />
                {/* Horizontal line from vertical to right edge */}
                <span
                    className="absolute"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: mid - TREE_LINE_W / 2,
                        right: 0,
                        top: `calc(50% - ${TREE_LINE_W / 2}px)`,
                        height: TREE_LINE_W,
                        backgroundColor: TREE_COLOR,
                    }}
                />
            </span>
        </span>
    )
}

function SpanDetailPanel({ span }: { span: Span }): JSX.Element {
    const status = STATUS_CODE_LABELS[span.status_code] ?? { label: String(span.status_code), type: 'default' as const }
    const isError = span.status_code === 2

    return (
        <div className={`border-t bg-surface-primary px-4 py-3 text-xs ${isError ? 'border-l-2 border-l-danger' : ''}`}>
            <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
                <span className="text-muted font-medium">Service</span>
                <span className="font-mono">{span.service_name}</span>
                <span className="text-muted font-medium">Operation</span>
                <span className="font-mono">{span.name}</span>
                <span className="text-muted font-medium">Duration</span>
                <span className="font-mono">{formatDuration(span.duration_nano)}</span>
                <span className="text-muted font-medium">Kind</span>
                <span>{SPAN_KIND_LABELS[span.kind] ?? span.kind}</span>
                <span className="text-muted font-medium">Status</span>
                <span>
                    <LemonTag type={status.type} size="small">
                        {status.label}
                    </LemonTag>
                </span>
                <span className="text-muted font-medium">Span ID</span>
                <span className="font-mono">{span.span_id}</span>
                {span.parent_span_id && (
                    <>
                        <span className="text-muted font-medium">Parent ID</span>
                        <span className="font-mono">{span.parent_span_id}</span>
                    </>
                )}
                <span className="text-muted font-medium">Start</span>
                <span className="font-mono">{span.timestamp}</span>
                <span className="text-muted font-medium">End</span>
                <span className="font-mono">{span.end_time}</span>
            </div>
        </div>
    )
}

export function TraceFlameChart({ spans }: TraceFlameChartProps): JSX.Element {
    const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null)
    const [cursorPct, setCursorPct] = useState<number | null>(null)
    const [labelColumnWidth, setLabelColumnWidth] = useState(
        () => readStoredLabelColumnWidth() ?? DEFAULT_LABEL_COLUMN_WIDTH
    )
    const labelResizeActiveRef = useRef(false)
    const labelSplitterDragCleanupRef = useRef<(() => void) | null>(null)
    const timelineRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        return () => {
            labelSplitterDragCleanupRef.current?.()
        }
    }, [])
    const serviceColorMap = useMemo(() => buildServiceColorMap(spans), [spans])
    const tree = useMemo(() => buildSpanTree(spans), [spans])
    const flatSpans = useMemo(() => flattenTree(tree), [tree])

    const { traceStartUs, traceDurationUs } = useMemo(() => {
        if (spans.length === 0) {
            return { traceStartUs: 0, traceDurationUs: 0 }
        }
        const startTimesUs = spans.map((s) => parseTimestampUs(s.timestamp))
        const endTimesUs = spans.map((s) => parseTimestampUs(s.timestamp) + s.duration_nano / 1_000)
        const traceStartUs = Math.min(...startTimesUs)
        const traceEndUs = Math.max(...endTimesUs)
        return { traceStartUs, traceDurationUs: traceEndUs - traceStartUs }
    }, [spans])

    // Pre-compute snap points (span start/end as percentages of trace duration)
    const snapPointsPct = useMemo(() => {
        if (traceDurationUs <= 0) {
            return []
        }
        const points = new Set<number>()
        for (const s of spans) {
            const spanStartUs = parseTimestampUs(s.timestamp)
            points.add(((spanStartUs - traceStartUs) / traceDurationUs) * 100)
            points.add(((spanStartUs + s.duration_nano / 1_000 - traceStartUs) / traceDurationUs) * 100)
        }
        return [...points].sort((a, b) => a - b)
    }, [spans, traceStartUs, traceDurationUs])

    const SNAP_THRESHOLD_PX = 6

    const persistLabelColumnWidth = useCallback((width: number): void => {
        try {
            window.localStorage.setItem(LABEL_COLUMN_WIDTH_STORAGE_KEY, String(width))
        } catch {
            // Quota or private mode
        }
    }, [])

    const handleLabelSplitterMouseDown = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()
            setCursorPct(null)
            labelResizeActiveRef.current = true
            document.body.classList.add('is-resizing')
            const startX = e.clientX
            const startWidth = labelColumnWidth
            let lastWidth = startWidth

            const onMove = (ev: MouseEvent): void => {
                lastWidth = clampLabelColumnWidth(startWidth + (ev.clientX - startX))
                setLabelColumnWidth(lastWidth)
            }
            const onUp = (): void => {
                labelSplitterDragCleanupRef.current = null
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
                document.body.classList.remove('is-resizing')
                labelResizeActiveRef.current = false
                persistLabelColumnWidth(lastWidth)
            }
            labelSplitterDragCleanupRef.current = onUp
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [labelColumnWidth, persistLabelColumnWidth]
    )

    const handleLabelSplitterKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault()
                const delta = e.key === 'ArrowLeft' ? -10 : 10
                setLabelColumnWidth((w) => {
                    const next = clampLabelColumnWidth(w + delta)
                    persistLabelColumnWidth(next)
                    return next
                })
            }
        },
        [persistLabelColumnWidth]
    )

    const handleTimelineMouseMove = useCallback(
        (e: React.MouseEvent) => {
            if (labelResizeActiveRef.current) {
                return
            }
            const timeline = timelineRef.current
            if (!timeline) {
                return
            }
            const rect = timeline.getBoundingClientRect()
            const x = e.clientX - rect.left
            if (x < 0 || x > rect.width) {
                setCursorPct(null)
                return
            }
            let pct = Math.max(0, Math.min(100, (x / rect.width) * 100))

            // Snap to nearest span edge if within threshold
            const pxPerPct = rect.width / 100
            for (const snapPct of snapPointsPct) {
                if (Math.abs(pct - snapPct) * pxPerPct <= SNAP_THRESHOLD_PX) {
                    pct = snapPct
                    break
                }
            }

            setCursorPct(pct)
        },
        [snapPointsPct]
    )

    const handleTimelineMouseLeave = useCallback(() => {
        setCursorPct(null)
    }, [])

    if (spans.length === 0) {
        return <div className="text-muted p-4">No spans in this trace</div>
    }

    const ticks = getTimelineTicks(traceDurationUs)

    const cursorTimeUs = cursorPct !== null ? (cursorPct / 100) * traceDurationUs : null

    return (
        <div
            className="flex flex-col relative"
            onMouseMove={handleTimelineMouseMove}
            onMouseLeave={handleTimelineMouseLeave}
        >
            {/* Full-height cursor line overlay */}
            {cursorPct !== null && (
                <div
                    className="absolute top-0 bottom-0 border-l border-dashed border-primary pointer-events-none z-20"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `calc(${labelColumnWidth}px + (100% - ${labelColumnWidth}px) * ${cursorPct / 100})`,
                    }}
                />
            )}

            {/* Timeline header */}
            <div className="flex border-b border-border sticky top-0 bg-surface-primary z-10">
                <div
                    className="shrink-0 text-xs font-medium text-muted px-2 flex items-center border-r border-border"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: labelColumnWidth }}
                >
                    Span
                </div>
                <div className="relative grow h-7" ref={timelineRef}>
                    {(cursorPct === null || cursorPct > 5) && (
                        <span className="absolute left-1 top-1/2 -translate-y-1/2 text-[10px] text-muted">0</span>
                    )}
                    {ticks
                        .filter((tickUs) => {
                            const pct = (tickUs / traceDurationUs) * 100
                            return pct > 5 && pct < 90
                        })
                        .map((tickUs) => {
                            const pct = (tickUs / traceDurationUs) * 100
                            return (
                                <span
                                    key={tickUs}
                                    className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 text-[10px] text-muted"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ left: `${pct}%` }}
                                >
                                    {formatDuration(tickUs * 1_000)}
                                </span>
                            )
                        })}
                    {(cursorPct === null || cursorPct < 95) && (
                        <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] text-muted">
                            {formatDuration(traceDurationUs * 1_000)}
                        </span>
                    )}
                    {/* Cursor time label in header */}
                    {cursorPct !== null && cursorTimeUs !== null && (
                        <span
                            className={`absolute bottom-0 text-[10px] font-mono font-medium pointer-events-none ${
                                cursorPct < 50 ? 'translate-x-1' : '-translate-x-full -ml-1'
                            }`}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${cursorPct}%` }}
                        >
                            {formatDuration(cursorTimeUs * 1_000)}
                        </span>
                    )}
                </div>
            </div>

            {/* Span rows */}
            {flatSpans.map((node) => {
                const { span } = node
                const spanStartUs = parseTimestampUs(span.timestamp)
                const spanDurationUs = span.duration_nano / 1_000
                const leftPct =
                    traceDurationUs > 0 ? Math.max(((spanStartUs - traceStartUs) / traceDurationUs) * 100, 0) : 0
                const rawWidthPct = traceDurationUs > 0 ? (spanDurationUs / traceDurationUs) * 100 : 100
                const widthPct = Math.max(Math.min(rawWidthPct, 100 - leftPct), 0.3)

                const isError = span.status_code === 2
                const isUnmatched = !span.matched_filter
                const seriesIndex = serviceColorMap.get(span.service_name) ?? 0
                const seriesColor = isError ? ERROR_COLOR : getSeriesColor(seriesIndex)
                const barColor = isUnmatched ? 'var(--border)' : seriesColor
                const isSelected = selectedSpanId === span.uuid

                return (
                    <div key={span.uuid}>
                        <div
                            className={`flex items-stretch cursor-pointer transition-colors ${
                                isSelected ? 'bg-surface-primary-active' : 'hover:bg-surface-primary-hover'
                            }`}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ minHeight: ROW_HEIGHT }}
                            role="button"
                            tabIndex={0}
                            aria-pressed={isSelected}
                            onClick={() => setSelectedSpanId(isSelected ? null : span.uuid)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    setSelectedSpanId(isSelected ? null : span.uuid)
                                }
                            }}
                        >
                            {/* Label column */}
                            <div
                                className="shrink-0 flex items-center overflow-hidden border-r border-border px-2"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: labelColumnWidth }}
                            >
                                <TreeIndent node={node} />
                                {isError && (
                                    <Tooltip title="This span has an error status">
                                        <IconWarning className="text-danger shrink-0 mr-1" fontSize={14} />
                                    </Tooltip>
                                )}
                                <Tooltip title={span.name}>
                                    <span
                                        className={`text-xs truncate ${isError ? 'text-danger font-semibold' : 'font-medium'} ${isUnmatched ? 'opacity-40' : ''}`}
                                    >
                                        {span.name}
                                    </span>
                                </Tooltip>
                            </div>

                            {/* Timeline column */}
                            <div
                                className="relative grow self-center"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: ROW_HEIGHT - 8 }}
                            >
                                {/* Grid lines */}
                                {ticks.map((tickUs) => {
                                    const pct = (tickUs / traceDurationUs) * 100
                                    return (
                                        <span
                                            key={tickUs}
                                            className="absolute top-0 bottom-0 border-l border-border"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ left: `${pct}%` }}
                                        />
                                    )
                                })}

                                {/* Span bar */}
                                <Tooltip
                                    title={
                                        <span>
                                            <strong>{span.name}</strong>
                                            <br />
                                            {span.service_name} · {formatDuration(span.duration_nano)}
                                            {isError ? ' · Error' : ''}
                                        </span>
                                    }
                                >
                                    <div
                                        className="absolute h-full flex items-center px-1.5 overflow-hidden"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            left: `${leftPct}%`,
                                            width: `${widthPct}%`,
                                            minWidth: 2,
                                            backgroundColor: `color-mix(in srgb, ${barColor} 20%, transparent)`,
                                            borderLeft: `1px solid ${barColor}`,
                                        }}
                                    >
                                        <span
                                            className={`text-[11px] truncate whitespace-nowrap flex items-center gap-1.5 ${isUnmatched ? 'opacity-40' : ''}`}
                                        >
                                            <span className="text-muted-alt font-medium">{span.service_name}</span>
                                            <span className="text-muted">{formatDuration(span.duration_nano)}</span>
                                        </span>
                                    </div>
                                </Tooltip>
                            </div>
                        </div>

                        {/* Detail panel */}
                        {isSelected && <SpanDetailPanel span={span} />}
                    </div>
                )
            })}

            {/* Full-height splitter between label column and timeline */}
            <div
                role="separator"
                aria-label="Resize span name column"
                aria-orientation="vertical"
                aria-valuenow={labelColumnWidth}
                aria-valuemin={MIN_LABEL_COLUMN_WIDTH}
                aria-valuemax={MAX_LABEL_COLUMN_WIDTH}
                tabIndex={0}
                className="absolute top-0 bottom-0 z-30 cursor-ew-resize touch-none hover:bg-accent-highlight-primary/30"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: labelColumnWidth - LABEL_SPLITTER_HIT_PX / 2,
                    width: LABEL_SPLITTER_HIT_PX,
                }}
                onMouseDown={handleLabelSplitterMouseDown}
                onKeyDown={handleLabelSplitterKeyDown}
            />
        </div>
    )
}
