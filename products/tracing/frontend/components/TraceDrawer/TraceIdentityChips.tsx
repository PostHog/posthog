import { LemonTag } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import type { TraceIdentity } from '../../traceIdentity'

export interface TraceIdentityChipsProps {
    identity: TraceIdentity
    /** Trace start, used to seek the recording to just before the trace ran. */
    timestamp: string | null
}

// Who the open trace belongs to. The person and the recording are properties of the trace, not of
// the inspected span, so this sits above the waterfall and does not change as the user walks spans.
// Server-only traffic carries no identity, and then this renders nothing.
// Modeled on AI Observability's trace-scene PersonChip.
export function TraceIdentityChips({ identity, timestamp }: TraceIdentityChipsProps): JSX.Element | null {
    if (!identity.distinctId && !identity.sessionId) {
        return null
    }

    return (
        <div className="flex items-center gap-2 flex-wrap pb-2" data-attr="tracing-trace-identity">
            {identity.distinctId && (
                <LemonTag size="small" className="bg-surface-primary">
                    <span className="sr-only">Person</span>
                    <PersonDisplay person={{ distinct_id: identity.distinctId }} withIcon="sm" noEllipsis />
                </LemonTag>
            )}
            {identity.sessionId && (
                <ViewRecordingButton
                    sessionId={identity.sessionId}
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
