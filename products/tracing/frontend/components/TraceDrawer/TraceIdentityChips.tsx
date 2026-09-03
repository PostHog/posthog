import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { tracingViewerLogic } from '../../tracingViewerLogic'

export interface TraceIdentityChipsProps {
    /** Trace start, used to seek the recording to just before the trace ran. */
    timestamp: string | null
}

// Who the open trace belongs to. The person and the recording are properties of the trace, not of
// the inspected span, so this sits above the waterfall and does not change as the user walks spans.
// Server-only traffic carries no identity, and then this renders nothing.
// Modeled on AI Observability's trace-scene PersonChip.
export function TraceIdentityChips({ timestamp }: TraceIdentityChipsProps): JSX.Element | null {
    const { traceIdentity } = useValues(tracingViewerLogic)

    if (!traceIdentity.distinctId && !traceIdentity.sessionId) {
        return null
    }

    return (
        <div className="flex items-center gap-2 flex-wrap pb-2" data-attr="tracing-trace-identity">
            {traceIdentity.distinctId && (
                <LemonTag size="small" className="bg-surface-primary">
                    <span className="sr-only">Person</span>
                    <PersonDisplay person={{ distinct_id: traceIdentity.distinctId }} withIcon="sm" noEllipsis />
                </LemonTag>
            )}
            {traceIdentity.sessionId && (
                <ViewRecordingButton
                    sessionId={traceIdentity.sessionId}
                    timestamp={timestamp ?? undefined}
                    openPlayerIn={RecordingPlayerType.Modal}
                    variant={ViewRecordingButtonVariant.Link}
                    checkRecordingExists
                    data-attr="tracing-trace-view-recording"
                />
            )}
        </div>
    )
}
