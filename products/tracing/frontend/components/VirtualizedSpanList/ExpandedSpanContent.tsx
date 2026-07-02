import { formatDuration } from '../../TraceWaterfallView'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from '../../types'
import type { Span } from '../../types'
import { SpanAttributes } from './SpanAttributes'

export interface ExpandedSpanContentProps {
    span: Span
    /**
     * Render the "Span details" KVP table alongside the attributes. The drawer's summary header
     * already surfaces these facts, so it passes false. @default true
     */
    showDetails?: boolean
}

export function ExpandedSpanContent({ span, showDetails = true }: ExpandedSpanContentProps): JSX.Element {
    const status = STATUS_CODE_LABELS[span.status_code]

    // The OTel attributes the user set on the span — the thing the row is here to surface.
    const attributes = span.attributes ?? {}

    // The span's intrinsic identifying detail, shown alongside the user attributes.
    const details: Record<string, string> = {
        'span.id': span.span_id,
        'parent.span.id': span.parent_span_id || '',
        'trace.id': span.trace_id,
        'service.name': span.service_name,
        'span.kind': SPAN_KIND_LABELS[span.kind] ?? String(span.kind),
        'status.code': status?.label ?? String(span.status_code),
        duration: formatDuration(span.duration_nano),
        'start.time': new Date(span.timestamp).toISOString(),
        'end.time': new Date(span.end_time).toISOString(),
    }

    return (
        <div className="flex flex-col gap-2 p-2 bg-primary border-t border-border">
            <SpanAttributes title="Attributes" attributes={attributes} emptyLabel="No attributes set on this span" />
            {/* Sibling section after the span attributes — same split the logs detail view uses.
                Often absent (non-k8s / no resource attrs), so hidden when empty to avoid noise. */}
            {Object.keys(span.resource_attributes ?? {}).length > 0 && (
                <SpanAttributes
                    title="Resource attributes"
                    attributes={span.resource_attributes}
                    emptyLabel="No resource attributes on this span"
                />
            )}
            {showDetails && <SpanAttributes title="Span details" attributes={details} />}
        </div>
    )
}
