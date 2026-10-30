import { type MouseEvent, useMemo } from 'react'

import { IconChevronRight, IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { parseTimestampUs } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import type { TraceRunToggleMethod, TraceViewTimeline } from '../TraceView/traceViewLogic'
import { LOG_MARK_TAG_TYPE, TraceDialogLogMark } from './TraceDialogLogMark'
import type { TraceDialogSource } from './traceDialogOpenLogic'
import { summarizeRun, type TraceDialogRow } from './traceDialogRows'
import { indentPx, MAX_VISUAL_DEPTH, TraceDialogTreeLines } from './TraceDialogTreeLines'

const ERROR_COLOR = 'var(--danger)'

export interface TraceDialogSpanRowProps {
    row: Extract<TraceDialogRow, { kind: 'span' | 'chain' | 'run' }>
    timeline: TraceViewTimeline
    serviceColorMap: Map<string, number>
    isSelected: boolean
    /** Set only on the span that emitted the record the dialog was opened from. */
    openedAtUs: number | null
    openedFrom: TraceDialogSource | null
    /** The row is outside the operation the Operations tab highlights. */
    isDimmed: boolean
    /** How many spans sit under this one. Zero for a span with no children. */
    descendantCount: number
    isCollapsed: boolean
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onToggleChain: (spanId: string) => void
    /** Takes the id of the run's first span. */
    onToggleRun: (spanId: string, method: TraceRunToggleMethod) => void
}

// Enter or Space on a focused button fires a click without a pointer press, which leaves `detail` at 0.
function toggleMethod(event: MouseEvent): TraceRunToggleMethod {
    return event.detail === 0 ? 'key' : 'click'
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
    isDimmed,
    descendantCount,
    isCollapsed,
    onSelect,
    onToggleCollapsed,
    onToggleChain,
    onToggleRun,
}: TraceDialogSpanRowProps): JSX.Element {
    const node = row.kind === 'span' ? row.node : row.nodes[0]
    const chainLast = row.kind === 'chain' ? row.nodes[row.nodes.length - 1] : null
    const openChainLength = row.kind === 'span' ? row.openChainLength : undefined
    const openRunLength = row.kind === 'span' ? row.openRunLength : undefined
    const runNodes = row.kind === 'run' ? row.nodes : null
    // A run can hold thousands of spans, and the list renders its rows again on every scroll and selection. A row
    // object stays the same until the rows rebuild after a fold, an expand or a new page of spans, so this pass
    // over the members runs once per run and not once per render.
    const run = useMemo(() => (runNodes ? summarizeRun(runNodes) : null), [runNodes])
    const runCountText = runNodes ? humanFriendlyNumber(runNodes.length) : null
    const { span, isMissingParent = false } = node
    const name = chainLast ? `${span.name} › … › ${chainLast.span.name}` : span.name
    const startUs = run ? run.startUs : parseTimestampUs(span.timestamp)
    const durationUs = run ? run.endUs - run.startUs : span.duration_nano / 1_000
    const leftPct = Math.max(percentOfTrace(startUs, timeline), 0)
    const widthPct = Math.max(
        Math.min(timeline.durationUs > 0 ? (durationUs / timeline.durationUs) * 100 : 100, 100 - leftPct),
        0.3
    )
    // A folded chain or run shows an error when any span in it errored, not only its first.
    const isError = run
        ? run.errorCount > 0
        : (row.kind === 'chain' ? row.nodes : [node]).some((member) => member.span.status_code === 2)
    // A folded run also hides the spans under its own. An error there gets only the icon, so that a failure under
    // the calls reads apart from a failed call.
    const hasNestedError = !!run && run.nestedErrorCount > 0
    const serviceColor = getSeriesColor(serviceColorMap.get(span.service_name) ?? 0)
    const barColor = isDimmed ? 'var(--border)' : isError ? ERROR_COLOR : serviceColor
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
            {run ? (
                // Opening a run never selects a span, so the inspector stays on the span the person picked.
                <button
                    type="button"
                    className="absolute inset-0 cursor-pointer"
                    aria-expanded={false}
                    aria-label={`Show ${runCountText} ${span.name} spans`}
                    title={[
                        `${span.name} ×${runCountText} · ${span.service_name}`,
                        `${runCountText} spans, ${formatDuration(run.totalDurationNano)} in total`,
                        `+${formatDuration((run.startUs - timeline.startUs) * 1_000)} to +${formatDuration(
                            (run.endUs - timeline.startUs) * 1_000
                        )} from the trace start`,
                        ...(run.errorCount > 0 ? [`${humanFriendlyNumber(run.errorCount)} with an error status`] : []),
                        ...(run.nestedErrorCount > 0
                            ? [
                                  `${humanFriendlyNumber(run.nestedErrorCount)} nested ${
                                      run.nestedErrorCount === 1 ? 'span' : 'spans'
                                  } with an error status`,
                              ]
                            : []),
                    ].join('\n')}
                    onClick={(event) => onToggleRun(span.span_id, toggleMethod(event))}
                    // pinned: data-attr value, because renaming it breaks autocapture dashboards and Playwright selectors
                    data-attr="tracing-trace-expand-run"
                />
            ) : (
                <button
                    type="button"
                    className="absolute inset-0 cursor-pointer"
                    aria-pressed={isSelected}
                    aria-label={span.name}
                    title={isMissingParent ? name : `${name} · ${span.service_name}`}
                    onClick={() => onSelect(span.span_id)}
                    data-attr="trace-dialog-span-row"
                />
            )}
            <span className="pointer-events-none relative w-16 shrink-0 px-2 font-mono text-muted" translate="no">
                +{formatDuration(Math.max(startUs - timeline.startUs, 0) * 1_000)}
            </span>
            <span
                className="pointer-events-none relative self-stretch w-96 shrink min-w-48 flex items-center gap-1.5 pr-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) }}
            >
                <TraceDialogTreeLines row={row} />
                {!!openRunLength && (
                    // The open counterpart of the folded run's chip. Its own collapse chip, if any, follows it.
                    <button
                        type="button"
                        className="pointer-events-auto relative shrink-0 flex items-center gap-0.5 h-5 pl-0.5 pr-1.5 rounded border border-dashed border-accent bg-surface-primary text-[11px] font-semibold text-accent hover:bg-accent-highlight-secondary"
                        aria-expanded
                        aria-label={`Fold ${humanFriendlyNumber(openRunLength)} ${span.name} spans`}
                        // Next to the span's own collapse chip, the two chips look alike.
                        title={`Fold ${humanFriendlyNumber(openRunLength)} ${span.name} spans`}
                        onClick={(event) => onToggleRun(span.span_id, toggleMethod(event))}
                        // pinned: data-attr value, because renaming it breaks autocapture dashboards and Playwright selectors
                        data-attr="tracing-trace-fold-run"
                    >
                        <IconChevronRight className="rotate-90" />
                        {/* "×" like the folded run's label, so the count reads as repeats, not as nested spans. */}
                        <span translate="no">×{humanFriendlyNumber(openRunLength)}</span>
                    </button>
                )}
                {runNodes ? (
                    // The whole row opens the run, so this only marks it as folded, in the style of a folded chain.
                    <span
                        className="relative shrink-0 flex items-center h-5 pl-0.5 pr-0.5 rounded border border-dashed border-accent bg-surface-primary text-accent"
                        aria-hidden
                    >
                        <IconChevronRight />
                    </span>
                ) : chainLast ? (
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
                        descendantCount === 0 && !chainLast && !runNodes && !openRunLength && 'w-4'
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
                {(isError || hasNestedError) && (
                    <IconWarning
                        className="shrink-0 text-danger"
                        fontSize={14}
                        aria-label={isError ? 'Error' : 'Error in nested spans'}
                    />
                )}
                <span
                    className={cn(
                        'relative truncate font-mono',
                        (isError || isMissingParent) && 'text-danger',
                        chainLast && 'text-secondary',
                        isSelected && 'font-semibold',
                        isDimmed && 'opacity-40'
                    )}
                    translate="no"
                >
                    {name}
                </span>
                {runCountText && (
                    <span
                        className={cn('relative shrink-0 font-mono text-secondary', isDimmed && 'opacity-40')}
                        translate="no"
                    >
                        ×{runCountText}
                    </span>
                )}
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
                {isMissingParent ? '' : formatDuration(run ? durationUs * 1_000 : span.duration_nano)}
            </span>
        </div>
    )
}
