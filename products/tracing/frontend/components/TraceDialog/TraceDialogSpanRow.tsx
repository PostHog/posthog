import { IconWarning } from '@posthog/icons'

import { getSeriesColor } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'

import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import type { TraceDialogTimeline } from './traceDialogLogic'

const INDENT_PX = 16
const ERROR_COLOR = 'var(--danger)'

export interface TraceDialogSpanRowProps {
    node: SpanNode
    timeline: TraceDialogTimeline
    serviceColorMap: Map<string, number>
    isSelected: boolean
    /** Set only on the span that emitted the record the dialog was opened from. */
    openedAtUs: number | null
    onSelect: (spanId: string) => void
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
    onSelect,
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
        <button
            type="button"
            className={cn(
                'flex items-center w-full h-full text-left text-xs border-l-[3px] cursor-pointer',
                isSelected
                    ? 'bg-surface-primary-active border-l-accent'
                    : 'border-l-transparent hover:bg-surface-primary-hover'
            )}
            aria-pressed={isSelected}
            onClick={() => onSelect(span.span_id)}
            data-attr="trace-dialog-span-row"
        >
            <span className="w-16 shrink-0 px-2 font-mono text-muted" translate="no">
                +{formatDuration(Math.max(startUs - timeline.startUs, 0) * 1_000)}
            </span>
            <span
                className="w-80 shrink-0 flex items-center gap-1.5 min-w-0 pr-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: node.depth * INDENT_PX }}
            >
                {!isMissingParent && (
                    <span
                        className="size-2 rounded-full shrink-0"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: serviceColor }}
                        aria-hidden
                    />
                )}
                <span className="shrink-0 max-w-28 truncate text-muted-alt" translate="no">
                    {span.service_name}
                </span>
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
            <span className="relative grow self-stretch my-1.5" aria-hidden>
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
            <span className="w-20 shrink-0 px-2 text-right font-mono text-muted" translate="no">
                {isMissingParent ? '' : formatDuration(span.duration_nano)}
            </span>
        </button>
    )
}
