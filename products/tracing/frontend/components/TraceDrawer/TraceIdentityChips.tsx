import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { resolveTraceIdentity } from '../../traceIdentity'
import { tracingCorrelationConfigLogic } from '../../tracingCorrelationConfigLogic'
import type { Span } from '../../types'

export interface TraceIdentityChipsProps {
    /** Every loaded span of the trace, because any one of them can carry the correlation keys. */
    spans: Span[]
    /** Trace start, used to seek the recording to just before the trace ran. */
    timestamp: string | null
}

// Who a trace belongs to, shown under the drawer title. The person and the recording are properties
// of the trace, not of the inspected span, so this sits above the waterfall and does not change as
// the user walks spans. Renders nothing when the trace carries no identity, which server-only
// traffic does. Modeled on AI Observability's trace-scene PersonChip.
export function TraceIdentityChips({ spans, timestamp }: TraceIdentityChipsProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { configuredDistinctIdKeys, configuredSessionIdKeys } = useValues(tracingCorrelationConfigLogic)

    // Scans every attribute of every loaded span, and the drawer re-renders on each mousemove of an
    // inspector resize drag, so keep the scan tied to the data instead of the render.
    const identity = useMemo(
        () => resolveTraceIdentity(spans, configuredDistinctIdKeys, configuredSessionIdKeys),
        [spans, configuredDistinctIdKeys, configuredSessionIdKeys]
    )

    if (!featureFlags[FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS]) {
        return null
    }
    if (!identity.distinctId && !identity.sessionId) {
        return null
    }

    return (
        <div className="flex items-center gap-2 flex-wrap mt-2" data-attr="tracing-trace-identity">
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
