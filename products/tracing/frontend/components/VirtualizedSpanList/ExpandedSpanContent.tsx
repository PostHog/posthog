import { useValues } from 'kea'

import { IconList } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { buildTraceLogsUrl } from '../../logsLink'
import { formatDuration } from '../../TraceFlameChart'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from '../../types'
import type { Span } from '../../types'
import { SpanAttributes } from './SpanAttributes'

export interface ExpandedSpanContentProps {
    span: Span
}

export function ExpandedSpanContent({ span }: ExpandedSpanContentProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
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
            {featureFlags[FEATURE_FLAGS.LOGS] && span.trace_id && (
                <div className="flex justify-end">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconList />}
                        data-attr="tracing-view-logs"
                        onClick={() => newInternalTab(buildTraceLogsUrl(span.trace_id, span.timestamp))}
                    >
                        View logs
                    </LemonButton>
                </div>
            )}
            <SpanAttributes title="Attributes" attributes={attributes} emptyLabel="No attributes set on this span" />
            <SpanAttributes title="Span details" attributes={details} />
        </div>
    )
}
