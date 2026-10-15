import { IconChevronRight, IconWarning } from '@posthog/icons'

import { getSeriesColor } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'

import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import type { TraceDialogTimeline } from './traceDialogLogic'

export const INDENT_PX = 12
// Deeper spans stop indenting, so the name keeps room in the fixed-width span column.
export const MAX_INDENT_DEPTH = 10
const ERROR_COLOR = 'var(--danger)'

export interface TraceDialogSpanRowProps {
    node: SpanNode
    timeline: TraceDialogTimeline
    serviceColorMap: Map<string, number>
    isSelected: boolean
    /** Set only on the span that emitted the record the dialog was opened from. */
    openedAtUs: number | null
    /** How many spans sit under this one. Zero for a span with no children. */
    descendantCount: number
    isCollapsed: boolean
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
}

function percentOfTrace(us: number, timeline: TraceDialogTimeline): number {
    return timeline.durationUs > 0 ? ((us - timeline.startUs) / timeline.durationUs) * 100 : 0
}

export function TraceDialogSpanRow({
    node,
    timeline,
    serviceColorMap,
    isSelected,
    openedAtUs,
    descendantCount,
    isCollapsed,
    onSelect,
    onToggleCollapsed,
}: TraceDialogSpanRowProps): JSX.Element {
    const { span, isMissingParent = false } = node
    const startUs = parseTimestampUs(span.timestamp)
    const leftPct = Math.max(percentOfTrace(startUs, timeline), 0)
    const widthPct = Math.max(
        Math.min(
            timeline.durationUs > 0 ? (span.duration_nano / 1_000 / timeline.durationUs) * 100 : 100,
            100 - leftPct
        ),
        0.3
    )
    const isError = span.status_code === 2
    const serviceColor = getSeriesColor(serviceColorMap.get(span.service_name) ?? 0)
    const barColor = isError ? ERROR_COLOR : serviceColor
    const openedAtPct = openedAtUs != null ? Math.min(Math.max(percentOfTrace(openedAtUs, timeline), 0), 100) : null

    return (
        // The collapse toggle cannot sit inside the select button, so the button fills the row from
        // behind and the row's content lets clicks through to it.
        <div
            className={cn(
                'relative flex items-center w-full h-full text-xs border-l-[3px]',
                isSelected
                    ? 'bg-surface-primary-active border-l-accent'
                    : 'border-l-transparent hover:bg-surface-primary-hover'
            )}
        >
            <button
                type="button"
                className="absolute inset-0 cursor-pointer"
                aria-pressed={isSelected}
                aria-label={span.name}
                title={isMissingParent ? span.name : `${span.name} · ${span.service_name}`}
                onClick={() => onSelect(span.span_id)}
                data-attr="trace-dialog-span-row"
            />
            <span className="pointer-events-none relative w-16 shrink-0 px-2 font-mono text-muted" translate="no">
                +{formatDuration(Math.max(startUs - timeline.startUs, 0) * 1_000)}
            </span>
            <span
                className="pointer-events-none relative w-80 shrink-0 flex items-center gap-1.5 min-w-0 pr-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: Math.min(node.depth, MAX_INDENT_DEPTH) * INDENT_PX }}
            >
                {descendantCount > 0 ? (
                    <button
                        type="button"
                        className="pointer-events-auto shrink-0 flex items-center gap-0.5 h-5 pl-0.5 pr-1 rounded border border-primary bg-surface-primary text-[11px] font-semibold text-secondary hover:border-secondary hover:text-primary"
                        aria-expanded={!isCollapsed}
                        aria-label={`${isCollapsed ? 'Show' : 'Hide'} ${descendantCount} nested ${
                            descendantCount === 1 ? 'span' : 'spans'
                        }`}
                        onClick={() => onToggleCollapsed(span.span_id)}
                        data-attr="trace-dialog-span-collapse"
                    >
                        <IconChevronRight className={cn('transition-transform', !isCollapsed && 'rotate-90')} />
                        {descendantCount.toLocaleString()}
                    </button>
                ) : (
                    <span className="w-5 shrink-0" aria-hidden />
                )}
                {!isMissingParent && (
                    <span
                        className="size-2 rounded-full shrink-0"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: serviceColor }}
                        aria-hidden
                    />
                )}
                {isError && <IconWarning className="shrink-0 text-danger" fontSize={14} aria-label="Error" />}
                <span
                    className={cn(
                        'truncate font-mono',
                        (isError || isMissingParent) && 'text-danger',
                        isSelected && 'font-semibold'
                    )}
                    translate="no"
                >
                    {span.name}
                </span>
            </span>
            <span className="pointer-events-none relative grow self-stretch my-1.5" aria-hidden>
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
                {openedAtPct != null && (
                    <span
                        className="absolute -inset-y-1 w-0.5 bg-accent"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: `${openedAtPct}%` }}
                        data-attr="trace-dialog-opened-at-marker"
                    />
                )}
            </span>
            <span
                className="pointer-events-none relative w-20 shrink-0 px-2 text-right font-mono text-muted"
                translate="no"
            >
                {isMissingParent ? '' : formatDuration(span.duration_nano)}
            </span>
        </div>
    )
}
