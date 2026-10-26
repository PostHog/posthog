import { ChevronRight, TriangleAlert } from 'lucide-react'
import { type ReactElement, useMemo, useState } from 'react'

import { cn, DescriptionList } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import {
    buildTraceDialogRows,
    countDescendantsById,
    rowConnectorLines,
    type TraceDialogRow,
} from 'products/tracing/frontend/components/TraceDialog/traceDialogRows'
import { indentPx, MAX_VISUAL_DEPTH } from 'products/tracing/frontend/components/TraceDialog/TraceDialogTreeLines'
import { buildSpanTree, getTimelineTicks, parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'
import { SPAN_KIND_LABELS, type Span } from 'products/tracing/frontend/types'

// `apm-trace-get` drops the attribute maps when called with excludeAttributes.
export type TraceWaterfallSpan = Omit<Span, 'attributes' | 'resource_attributes' | 'matched_filter'> & {
    attributes?: Record<string, string>
    resource_attributes?: Record<string, string>
    matched_filter?: boolean | number
    self_time_nano?: number
}

export interface TraceWaterfallData {
    results: TraceWaterfallSpan[]
    hasMore?: boolean
    _posthogUrl?: string
}

interface Timeline {
    startUs: number
    durationUs: number
}

const SERVICE_COLOR_COUNT = 8
const ERROR_COLOR = 'var(--destructive-foreground)'
const LINE_OFFSET_PX = 8

export function formatDuration(durationNano: number): string {
    const us = durationNano / 1_000
    if (us < 100) {
        return `${us.toFixed(1)}µs`
    }
    const ms = us / 1_000
    if (ms < 1000) {
        return `${ms.toFixed(ms < 10 ? 2 : 1)}ms`
    }
    return `${(ms / 1000).toFixed(2)}s`
}

function toSpan(span: TraceWaterfallSpan): Span {
    return {
        ...span,
        matched_filter: Boolean(span.matched_filter),
        attributes: span.attributes ?? {},
        resource_attributes: span.resource_attributes ?? {},
    }
}

function serviceColor(serviceIndexes: Map<string, number>, service: string): string {
    return `var(--posthog-chart-${((serviceIndexes.get(service) ?? 0) % SERVICE_COLOR_COUNT) + 1})`
}

function percentOfTrace(us: number, timeline: Timeline): number {
    return timeline.durationUs > 0 ? ((us - timeline.startUs) / timeline.durationUs) * 100 : 0
}

function TreeLines({ row }: { row: TraceDialogRow }): ReactElement | null {
    if (row.depth === 0 || row.depth > MAX_VISUAL_DEPTH) {
        return null
    }
    const parentLineX = indentPx(row.depth - 1) + LINE_OFFSET_PX
    return (
        <span className="absolute inset-y-0 left-0 pointer-events-none" aria-hidden>
            {rowConnectorLines(row).map((continues, level) =>
                continues ? (
                    <span
                        key={level}
                        className="absolute inset-y-0 w-px bg-border"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: indentPx(level) + LINE_OFFSET_PX }}
                    />
                ) : null
            )}
            <span
                className="absolute top-0 w-px bg-border"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: parentLineX, bottom: row.isLast ? '50%' : 0 }}
            />
            <span
                className="absolute top-1/2 h-px bg-border"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: parentLineX, width: indentPx(row.depth) - parentLineX }}
            />
        </span>
    )
}

const toggleClassName =
    'pointer-events-auto relative shrink-0 flex items-center gap-0.5 h-5 pl-0.5 pr-1.5 rounded border border-primary text-[11px] font-semibold text-primary'

interface SpanRowProps {
    row: Extract<TraceDialogRow, { kind: 'span' | 'chain' }>
    timeline: Timeline
    serviceIndexes: Map<string, number>
    isSelected: boolean
    descendantCount: number
    isCollapsed: boolean
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onToggleChain: (spanId: string) => void
}

function SpanRow({
    row,
    timeline,
    serviceIndexes,
    isSelected,
    descendantCount,
    isCollapsed,
    onSelect,
    onToggleCollapsed,
    onToggleChain,
}: SpanRowProps): ReactElement {
    const node = row.kind === 'chain' ? row.nodes[0]! : row.node
    const chainLast = row.kind === 'chain' ? row.nodes[row.nodes.length - 1] : null
    const openChainLength = row.kind === 'span' ? row.openChainLength : undefined
    const { span, isMissingParent = false } = node
    const name = chainLast ? `${span.name} › … › ${chainLast.span.name}` : span.name
    const startUs = parseTimestampUs(span.timestamp)
    const leftPct = Math.max(percentOfTrace(startUs, timeline), 0)
    const widthPct = Math.max(
        Math.min(
            timeline.durationUs > 0 ? (span.duration_nano / 1_000 / timeline.durationUs) * 100 : 100,
            100 - leftPct
        ),
        0.3
    )
    // A folded chain shows an error when any span in it errored, not only its first.
    const isError = (row.kind === 'chain' ? row.nodes : [node]).some((member) => member.span.status_code === 2)
    const color = serviceColor(serviceIndexes, span.service_name)
    const barColor = isError ? ERROR_COLOR : color

    return (
        // The toggles cannot sit inside the select button, so the button fills the row from behind.
        <div
            className={cn(
                'relative flex items-center w-full h-8 text-xs border-l-[3px]',
                isSelected ? 'bg-muted border-l-primary' : 'border-l-transparent hover:bg-muted/50'
            )}
            data-attr="trace-waterfall-span-row"
        >
            <button
                type="button"
                className="absolute inset-0 cursor-pointer"
                aria-pressed={isSelected}
                aria-label={span.name}
                title={isMissingParent ? name : `${name} · ${span.service_name}`}
                onClick={() => onSelect(span.span_id)}
            />
            <span className="pointer-events-none relative w-16 shrink-0 px-2 font-mono text-muted-foreground">
                +{formatDuration(Math.max(startUs - timeline.startUs, 0) * 1_000)}
            </span>
            <span
                className="pointer-events-none relative self-stretch w-2/5 shrink-0 min-w-40 flex items-center gap-1.5 pr-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) }}
            >
                <TreeLines row={row} />
                {chainLast ? (
                    <button
                        type="button"
                        className={cn(toggleClassName, 'border-dashed')}
                        aria-expanded={false}
                        aria-label={`Show ${row.kind === 'chain' ? row.nodes.length : 0} folded spans`}
                        onClick={() => onToggleChain(span.span_id)}
                    >
                        <ChevronRight size={12} />
                        {row.kind === 'chain' ? row.nodes.length.toLocaleString() : null}
                    </button>
                ) : descendantCount > 0 ? (
                    <button
                        type="button"
                        className={toggleClassName}
                        aria-expanded={!isCollapsed}
                        aria-label={`${isCollapsed ? 'Show' : 'Hide'} ${descendantCount} nested ${
                            descendantCount === 1 ? 'span' : 'spans'
                        }`}
                        onClick={() => onToggleCollapsed(span.span_id)}
                    >
                        <ChevronRight size={12} className={cn('transition-transform', !isCollapsed && 'rotate-90')} />
                        {descendantCount.toLocaleString()}
                    </button>
                ) : null}
                {/* A leaf's dot sits where a parent's toggle would, so the elbow ends at it. */}
                <span
                    className={cn(
                        'relative flex shrink-0 items-center justify-center',
                        descendantCount === 0 && !chainLast && 'w-4'
                    )}
                    aria-hidden
                >
                    {!isMissingParent && (
                        <span
                            className="size-2 rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: color }}
                        />
                    )}
                </span>
                {row.depth > MAX_VISUAL_DEPTH && (
                    <span className="relative shrink-0 rounded border px-1 font-mono text-[10px] text-muted-foreground">
                        L{row.depth}
                    </span>
                )}
                {isError && (
                    <TriangleAlert size={14} className="shrink-0 text-destructive-foreground" aria-label="Error" />
                )}
                <span
                    className={cn(
                        'relative truncate font-mono',
                        (isError || isMissingParent) && 'text-destructive-foreground',
                        chainLast && 'text-muted-foreground',
                        isSelected && 'font-semibold'
                    )}
                >
                    {name}
                </span>
                {openChainLength && (
                    <button
                        type="button"
                        className="pointer-events-auto relative ml-auto shrink-0 text-[11px] font-medium text-primary hover:underline"
                        onClick={() => onToggleChain(span.span_id)}
                    >
                        Fold {openChainLength}
                    </button>
                )}
            </span>
            <span className="pointer-events-none relative grow min-w-16 self-stretch my-1.5" aria-hidden>
                {!isMissingParent && (
                    <span
                        className="absolute inset-y-0"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `${leftPct}%`,
                            width: `${widthPct}%`,
                            minWidth: 2,
                            backgroundColor: `color-mix(in srgb, ${barColor} 20%, transparent)`,
                            borderLeft: `1px solid ${barColor}`,
                        }}
                    />
                )}
            </span>
            <span className="pointer-events-none relative w-20 shrink-0 px-2 text-right font-mono text-muted-foreground">
                {isMissingParent ? '' : formatDuration(span.duration_nano)}
            </span>
        </div>
    )
}

function MoreSpansRow({
    row,
    onShowAll,
}: {
    row: Extract<TraceDialogRow, { kind: 'more' }>
    onShowAll: (spanId: string) => void
}): ReactElement {
    return (
        // Same columns as the span row, so the tree lines on both line up at any width.
        <div className="flex items-center w-full h-8 text-xs text-muted-foreground border-l-[3px] border-l-transparent">
            <span className="w-16 shrink-0" aria-hidden />
            <span
                className="relative self-stretch w-2/5 shrink-0 min-w-40 flex items-center gap-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) + 22 }}
            >
                <TreeLines row={row} />
                <span className="relative">
                    {row.hiddenCount.toLocaleString()} more {row.hiddenCount === 1 ? 'span' : 'spans'}
                </span>
                <Button
                    variant="link"
                    size="sm"
                    className="h-auto px-0"
                    onClick={() => onShowAll(row.parent.span.span_id)}
                >
                    Show all
                </Button>
            </span>
            <span className="grow min-w-16" aria-hidden />
            <span className="w-20 shrink-0" aria-hidden />
        </div>
    )
}

function SelectedSpanDetails({ node, timeline }: { node: SpanNode; timeline: Timeline }): ReactElement {
    const span = node.span as Span & { self_time_nano?: number }
    if (node.isMissingParent) {
        return (
            <p className="text-xs text-muted-foreground">
                Span <span className="font-mono">{span.span_id}</span> is not in this trace. The spans under it point to
                it as their parent.
            </p>
        )
    }
    const attributes = Object.entries(span.attributes).sort(([a], [b]) => a.localeCompare(b))
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono font-semibold break-all">{span.name}</span>
                <Badge
                    variant={span.status_code === 2 ? 'destructive' : span.status_code === 1 ? 'success' : 'default'}
                >
                    {span.status_code === 2 ? 'Error' : span.status_code === 1 ? 'OK' : 'Unset'}
                </Badge>
            </div>
            <DescriptionList
                columns={2}
                items={[
                    { label: 'Service', value: span.service_name || '—' },
                    { label: 'Kind', value: SPAN_KIND_LABELS[span.kind] ?? String(span.kind) },
                    {
                        label: 'Start',
                        value: `+${formatDuration(Math.max(parseTimestampUs(span.timestamp) - timeline.startUs, 0) * 1_000)}`,
                    },
                    { label: 'Duration', value: formatDuration(span.duration_nano) },
                    ...(span.self_time_nano != null
                        ? [{ label: 'Self time', value: formatDuration(span.self_time_nano) }]
                        : []),
                    { label: 'Span ID', value: span.span_id },
                ]}
            />
            {attributes.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Attributes</span>
                    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-3 gap-y-0.5 text-xs font-mono">
                        {attributes.map(([key, value]) => (
                            <div key={key} className="contents">
                                <dt className="truncate text-muted-foreground" title={key}>
                                    {key}
                                </dt>
                                <dd className="break-all line-clamp-3">{value}</dd>
                            </div>
                        ))}
                    </dl>
                </div>
            )}
        </div>
    )
}

function addOrRemove(set: Set<string>, id: string): Set<string> {
    const next = new Set(set)
    if (!next.delete(id)) {
        next.add(id)
    }
    return next
}

function findNode(roots: SpanNode[], spanId: string | null): SpanNode | null {
    const stack = [...roots]
    while (stack.length > 0) {
        const node = stack.pop()!
        if (node.span.span_id === spanId) {
            return node
        }
        stack.push(...node.children)
    }
    return null
}

export function TraceWaterfallView({ data }: { data: TraceWaterfallData }): ReactElement {
    const spans = useMemo(() => data.results.map(toSpan), [data.results])
    const roots = useMemo(() => buildSpanTree(spans), [spans])
    const descendantCounts = useMemo(() => countDescendantsById(roots), [roots])
    const serviceIndexes = useMemo(
        () => new Map([...new Set(spans.map((span) => span.service_name))].sort().map((service, i) => [service, i])),
        [spans]
    )
    const timeline = useMemo((): Timeline => {
        if (spans.length === 0) {
            return { startUs: 0, durationUs: 0 }
        }
        const starts = spans.map((span) => parseTimestampUs(span.timestamp))
        const ends = spans.map((span, i) => starts[i]! + span.duration_nano / 1_000)
        const startUs = Math.min(...starts)
        return { startUs, durationUs: Math.max(...ends) - startUs }
    }, [spans])

    const rootSpan = spans.find((span) => span.is_root_span) ?? null
    const errorCount = spans.filter((span) => span.status_code === 2).length
    const serviceCount = serviceIndexes.size

    const [collapsedSpanIds, setCollapsedSpanIds] = useState<Set<string>>(() => new Set())
    const [fullChildListSpanIds, setFullChildListSpanIds] = useState<Set<string>>(() => new Set())
    const [openChainIds, setOpenChainIds] = useState<Set<string>>(() => new Set())
    const [selectedSpanId, setSelectedSpanId] = useState<string | null>(() => rootSpan?.span_id ?? null)

    const rows = useMemo(
        () => buildTraceDialogRows(roots, { collapsedSpanIds, fullChildListSpanIds, openChainIds, pinned: null }),
        [roots, collapsedSpanIds, fullChildListSpanIds, openChainIds]
    )
    const selectedNode = useMemo(() => findNode(roots, selectedSpanId), [roots, selectedSpanId])

    if (spans.length === 0) {
        return <div className="p-4 text-sm text-muted-foreground">No spans found for this trace.</div>
    }

    return (
        <div className="p-4 flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <span className="font-mono font-semibold break-all">{rootSpan?.name ?? 'Trace'}</span>
                <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                    <span>
                        {spans.length.toLocaleString()} {spans.length === 1 ? 'span' : 'spans'} ·{' '}
                        {serviceCount.toLocaleString()} {serviceCount === 1 ? 'service' : 'services'} ·{' '}
                        {formatDuration(timeline.durationUs * 1_000)}
                    </span>
                    {errorCount > 0 && (
                        <Badge variant="destructive">
                            {errorCount.toLocaleString()} {errorCount === 1 ? 'error' : 'errors'}
                        </Badge>
                    )}
                </div>
                {data.hasMore && (
                    <span className="text-xs text-muted-foreground">
                        Showing the first {spans.length.toLocaleString()} spans. Open the trace in PostHog to see all of
                        them.
                    </span>
                )}
            </div>
            <div className="@container border rounded-md overflow-hidden">
                <div className="flex items-center text-[11px] text-muted-foreground border-b py-1" aria-hidden>
                    <span className="w-16 shrink-0 px-2 border-l-[3px] border-l-transparent">Start</span>
                    <span className="w-2/5 shrink-0 min-w-40">Span</span>
                    <span className="relative grow min-w-16 h-4">
                        {getTimelineTicks(timeline.durationUs).map((tickUs, i) => (
                            <span
                                key={tickUs}
                                // A narrow frame has room for every other label only.
                                className={cn(
                                    'absolute -translate-x-1/2 font-mono',
                                    i % 2 === 0 && 'hidden @min-[36rem]:inline'
                                )}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ left: `${(tickUs / timeline.durationUs) * 100}%` }}
                            >
                                {formatDuration(tickUs * 1_000)}
                            </span>
                        ))}
                    </span>
                    <span className="w-20 shrink-0 px-2 text-right">Duration</span>
                </div>
                <div className="max-h-[420px] overflow-y-auto" role="list">
                    {rows.map((row) => {
                        if (row.kind === 'more') {
                            return (
                                <div key={`more-${row.parent.span.span_id}`} role="listitem">
                                    <MoreSpansRow
                                        row={row}
                                        onShowAll={(id) => setFullChildListSpanIds((ids) => new Set(ids).add(id))}
                                    />
                                </div>
                            )
                        }
                        const spanId = (row.kind === 'chain' ? row.nodes[0]! : row.node).span.span_id
                        return (
                            <div key={spanId} role="listitem">
                                <SpanRow
                                    row={row}
                                    timeline={timeline}
                                    serviceIndexes={serviceIndexes}
                                    isSelected={spanId === selectedSpanId}
                                    descendantCount={descendantCounts.get(spanId) ?? 0}
                                    isCollapsed={collapsedSpanIds.has(spanId)}
                                    onSelect={setSelectedSpanId}
                                    onToggleCollapsed={(id) => setCollapsedSpanIds((ids) => addOrRemove(ids, id))}
                                    onToggleChain={(id) => setOpenChainIds((ids) => addOrRemove(ids, id))}
                                />
                            </div>
                        )
                    })}
                </div>
            </div>
            {selectedNode && (
                <div className="border rounded-md p-3">
                    <SelectedSpanDetails node={selectedNode} timeline={timeline} />
                </div>
            )}
        </div>
    )
}
