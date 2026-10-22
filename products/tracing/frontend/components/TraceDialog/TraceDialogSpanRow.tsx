import { IconChevronRight, IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'

import { parseTimestampUs } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import type { TraceViewTimeline } from '../TraceView/traceViewLogic'
import type { TraceDialogSource } from './traceDialogLogic'
import { LOG_MARK_TAG_TYPE, TraceDialogLogMark } from './TraceDialogLogMark'
import type { TraceDialogRow } from './traceDialogRows'
import { indentPx, MAX_VISUAL_DEPTH, TraceDialogTreeLines } from './TraceDialogTreeLines'

const ERROR_COLOR = 'var(--danger)'

export interface TraceDialogSpanRowProps {
    row: Extract<TraceDialogRow, { kind: 'span' | 'chain' }>
    timeline: TraceViewTimeline
    serviceColorMap: Map<string, number>
    isSelected: boolean
    /** Set only on the span that emitted the record the dialog was opened from. */
    openedAtUs: number | null
    openedFrom: TraceDialogSource | null
    /** How many spans sit under this one. Zero for a span with no children. */
    descendantCount: number
    isCollapsed: boolean
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onToggleChain: (spanId: string) => void
}

// Clock skew between a service's logs and spans can put the log outside the span it names.
function logTimingLabel(logUs: number, startUs: number, durationUs: number): string {
    if (logUs < startUs) {
        return `written ${formatDuration((startUs - logUs) * 1_000)} before this span started`
    }
    if (logUs > startUs + durationUs) {
        return `written ${formatDuration((logUs - startUs - durationUs) * 1_000)} after this span ended`
    }
    return `+${formatDuration((logUs - startUs) * 1_000)} into this span`
}

function percentOfTrace(us: number, timeline: TraceViewTimeline): number {
    return timeline.durationUs > 0 ? ((us - timeline.startUs) / timeline.durationUs) * 100 : 0
}

export function TraceDialogSpanRow({
    row,
    timeline,
    serviceColorMap,
    isSelected,
    openedAtUs,
    openedFrom,
    descendantCount,
    isCollapsed,
    onSelect,
    onToggleCollapsed,
    onToggleChain,
}: TraceDialogSpanRowProps): JSX.Element {
    const node = row.kind === 'chain' ? row.nodes[0] : row.node
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
    const serviceColor = getSeriesColor(serviceColorMap.get(span.service_name) ?? 0)
    const barColor = isError ? ERROR_COLOR : serviceColor
    const openedAtPct =
        openedAtUs != null && openedFrom ? Math.min(Math.max(percentOfTrace(openedAtUs, timeline), 0), 100) : null

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
                title={isMissingParent ? name : `${name} · ${span.service_name}`}
                onClick={() => onSelect(span.span_id)}
                data-attr="trace-dialog-span-row"
            />
            <span className="pointer-events-none relative w-16 shrink-0 px-2 font-mono text-muted" translate="no">
                +{formatDuration(Math.max(startUs - timeline.startUs, 0) * 1_000)}
            </span>
            <span
                className="pointer-events-none relative self-stretch w-96 shrink min-w-48 flex items-center gap-1.5 pr-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) }}
            >
                <TraceDialogTreeLines row={row} />
                {chainLast ? (
                    <button
                        type="button"
                        className="pointer-events-auto relative shrink-0 flex items-center gap-0.5 h-5 pl-0.5 pr-1.5 rounded border border-dashed border-accent bg-surface-primary text-[11px] font-semibold text-accent hover:bg-accent-highlight-secondary"
                        aria-expanded={false}
                        aria-label={`Show ${row.kind === 'chain' ? row.nodes.length : 0} folded spans`}
                        onClick={() => onToggleChain(span.span_id)}
                        data-attr="trace-dialog-span-chain"
                    >
                        <IconChevronRight />
                        {row.kind === 'chain' ? row.nodes.length.toLocaleString() : null}
                    </button>
                ) : descendantCount > 0 ? (
                    <button
                        type="button"
                        className="pointer-events-auto relative shrink-0 flex items-center gap-0.5 h-5 pl-0.5 pr-1.5 rounded border border-accent bg-accent-highlight-secondary text-[11px] font-semibold text-accent hover:bg-accent-highlight-primary"
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
                            style={{ backgroundColor: serviceColor }}
                        />
                    )}
                </span>
                {row.depth > MAX_VISUAL_DEPTH && (
                    <span
                        className="relative shrink-0 rounded border px-1 font-mono text-[10px] text-muted"
                        translate="no"
                    >
                        L{row.depth}
                    </span>
                )}
                {isError && <IconWarning className="shrink-0 text-danger" fontSize={14} aria-label="Error" />}
                <span
                    className={cn(
                        'relative truncate font-mono',
                        (isError || isMissingParent) && 'text-danger',
                        chainLast && 'text-secondary',
                        isSelected && 'font-semibold'
                    )}
                    translate="no"
                >
                    {name}
                </span>
                {openedAtPct != null && openedFrom && (
                    <LemonTag
                        size="small"
                        type={LOG_MARK_TAG_TYPE[openedFrom.severity] ?? 'muted'}
                        className="relative shrink-0"
                        data-attr="trace-dialog-your-log-chip"
                    >
                        Your log
                    </LemonTag>
                )}
                {openChainLength && (
                    <button
                        type="button"
                        className="pointer-events-auto relative ml-auto shrink-0 text-[11px] font-medium text-accent hover:underline"
                        onClick={() => onToggleChain(span.span_id)}
                        data-attr="trace-dialog-span-chain-fold"
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
                {openedAtPct != null && openedFrom && (
                    <Tooltip
                        title={
                            <div className="flex flex-col gap-0.5 max-w-80">
                                <span className="text-xs opacity-75">
                                    {/* A missing parent has no real start or duration to measure the log against. */}
                                    Your log ·{' '}
                                    {isMissingParent
                                        ? ''
                                        : `${logTimingLabel(openedAtUs!, startUs, span.duration_nano / 1_000)} · `}
                                    {openedFrom.severity}
                                </span>
                                <span className="ph-replay-block ph-no-capture font-mono line-clamp-4" translate="no">
                                    {openedFrom.body}
                                </span>
                            </div>
                        }
                    >
                        <span
                            className="pointer-events-auto absolute top-1/2 -translate-x-1/2 -translate-y-1/2 flex"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${openedAtPct}%` }}
                            data-attr="trace-dialog-opened-at-marker"
                        >
                            <TraceDialogLogMark severity={openedFrom.severity} />
                        </span>
                    </Tooltip>
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
