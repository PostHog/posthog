import { useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { dayjs } from 'lib/dayjs'

import { deriveSpanSummary } from '../../spanSummary'
import { formatDuration } from '../../TraceWaterfallView'
import type { Span } from '../../types'

// A service indicator (not an error indicator — error state is the status badge's job). Colored
// from the waterfall's shared palette; neutral when the service isn't a span in this trace (e.g. an
// external peer), so we don't borrow an unrelated service's color.
function ServiceDot({ colorIndex }: { colorIndex: number | undefined }): JSX.Element {
    return (
        <span
            className="inline-block size-2 rounded-full shrink-0"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: colorIndex === undefined ? 'var(--border-bold)' : getSeriesColor(colorIndex) }}
        />
    )
}

// A labelled, copyable identifier. Trace/parent IDs live here (not just the span ID) because the
// summary header replaces the old "Span details" table — they're the only copyable home for the
// correlation handles a user needs to pivot across distributed-trace tooling.
function CopyableId({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <span>
            {label}:{' '}
            <CopyToClipboardInline
                explicitValue={value}
                description={label.toLowerCase()}
                iconSize="xsmall"
                iconPosition="end"
                className="font-mono"
            >
                {value}
            </CopyToClipboardInline>
        </span>
    )
}

// Adaptive summary of the inspected span, above the inspector tabs. Each piece renders only when
// the span carries the data (see deriveSpanSummary), so it reflows from a bare internal span up to
// a full HTTP-to-k8s call. Service dots reuse the waterfall's service palette for cross-pane consistency.
export function SpanSummaryHeader({
    span,
    serviceColorMap,
}: {
    span: Span
    serviceColorMap: Map<string, number>
}): JSX.Element {
    // Memoized so a parent resize-drag (re-renders every mousemove) doesn't re-scan the attributes.
    const summary = useMemo(() => deriveSpanSummary(span), [span])

    return (
        <div className="flex flex-col gap-1.5 px-1 pb-2" data-attr="tracing-span-summary">
            <div className="flex items-center gap-2">
                {/* min-w-0 lets the flex item shrink so a long operation ellipsizes instead of
                    shoving the status tag off; the tag holds its size. */}
                <span className="font-semibold truncate min-w-0">{summary.operation}</span>
                <LemonTag type={summary.status.type} className="shrink-0">
                    {summary.status.label}
                </LemonTag>
            </div>

            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <span className="flex items-center gap-1.5">
                    <ServiceDot colorIndex={serviceColorMap.get(summary.service)} />
                    <span>{summary.service}</span>
                    {summary.peerService && (
                        <>
                            <span aria-hidden>→</span>
                            <ServiceDot colorIndex={serviceColorMap.get(summary.peerService)} />
                            <span>{summary.peerService}</span>
                        </>
                    )}
                </span>
                <span>{formatDuration(summary.durationNano)}</span>
                {/* UTC to match the waterfall/sparkline (displayTimezone="UTC"). end shows time-only —
                    same day as start in all but pathological spans, so the date would just be noise. */}
                <span>
                    {dayjs(summary.timestamp).tz('UTC').format('MMM D HH:mm:ss.SSS')}
                    {' → '}
                    {dayjs(summary.endTimestamp).tz('UTC').format('HH:mm:ss.SSS')}
                </span>
            </div>

            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <CopyableId label="Span ID" value={summary.spanId} />
                <CopyableId label="Trace ID" value={summary.traceId} />
                {summary.parentSpanId && <CopyableId label="Parent span ID" value={summary.parentSpanId} />}
            </div>

            <div className="flex items-center gap-1.5 flex-wrap">
                {summary.type && <LemonTag type="muted">{summary.type}</LemonTag>}
                <LemonTag type="muted">{summary.kind}</LemonTag>
                {summary.cluster && <LemonTag>Cluster: {summary.cluster}</LemonTag>}
                {summary.pod && <LemonTag>Pod: {summary.pod}</LemonTag>}
            </div>
        </div>
    )
}
