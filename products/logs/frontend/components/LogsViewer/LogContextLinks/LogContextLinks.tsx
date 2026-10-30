import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { usableId } from 'lib/components/ViewTraceButton/usableId'
import { ViewTraceButton } from 'lib/components/ViewTraceButton/ViewTraceButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { buildLogErrorsLogicProps } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/Tabs/RelatedErrors/buildLogErrorsLogicProps'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getDistinctIdWithKey, getSessionIdFromLogAttributes } from 'products/logs/frontend/utils'
import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'
import type { TraceDialogEntryPoint } from 'products/tracing/frontend/components/TraceDialog/traceDialogOpenLogic'
import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'
import { type ErrorScope } from 'products/tracing/frontend/errorCorrelation'

import { LogErrorCount } from './LogErrorCount'
import { MissingLinkInvestigate } from './MissingLinkInvestigate'
import { MissingLink } from './missingLinkPrompt'

export type LogContextLinksSurface = 'drawer' | 'row'

// Frozen data-attr values: autocapture dashboards match on them, so the two surfaces keep different trace attrs.
const TRACE_DATA_ATTR: Record<LogContextLinksSurface, string> = {
    drawer: 'logs-details-view-trace',
    row: 'logs-row-view-trace',
}

const TRACE_DIALOG_ENTRY_POINT: Record<LogContextLinksSurface, TraceDialogEntryPoint> = {
    drawer: 'log_details',
    row: 'log_expanded_row',
}

export interface LogContextLinksProps {
    log: ParsedLogMessage
    surface: LogContextLinksSurface
    /** Called when the error count is clicked, with the scope the count was taken on. */
    onOpenRelatedErrors: (scope: ErrorScope) => void
    /** Closes the surface holding these links, so the AI side panel opened from them is not covered. */
    onLeave?: () => void
}

export function LogContextLinks({
    log,
    surface,
    onOpenRelatedErrors,
    onLeave,
}: LogContextLinksProps): JSX.Element | null {
    const { configuredSessionIdKeys, configuredDistinctIdKeys } = useValues(logsConfigLogic)

    const traceId = usableId(log.trace_id)
    const openTraceDialog = useOpenTraceDialog()
    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    const distinctId = getDistinctIdWithKey(log.attributes, log.resource_attributes, configuredDistinctIdKeys)?.value

    const { featureFlags } = useValues(featureFlagLogic)

    const canViewErrors = userHasAccess(AccessControlResourceType.ErrorTracking, AccessControlLevel.Viewer)
    const investigateEnabled = !!featureFlags[FEATURE_FLAGS.LOGS_MISSING_LINK_INVESTIGATE]
    const missing: MissingLink[] = investigateEnabled
        ? [!traceId && 'trace', !sessionId && 'session', !distinctId && 'person'].filter(
              (link): link is MissingLink => !!link
          )
        : []

    if (!investigateEnabled && !traceId && !sessionId && !distinctId) {
        return null
    }

    return (
        <div className="flex items-center gap-1 flex-wrap min-w-0">
            {traceId && (
                <ViewTraceButton
                    traceId={traceId}
                    spanId={log.span_id}
                    timestamp={log.timestamp}
                    onClick={(event) =>
                        openTraceDialog(
                            event,
                            { traceId, spanId: log.span_id, ts: log.timestamp },
                            {
                                entryPoint: TRACE_DIALOG_ENTRY_POINT[surface],
                                openedFrom: { body: log.cleanBody, severity: log.severity_text },
                            }
                        )
                    }
                    size="xsmall"
                    type="secondary"
                    data-attr={TRACE_DATA_ATTR[surface]}
                />
            )}
            {(traceId || sessionId) && canViewErrors && (
                <LogErrorCount
                    logicProps={buildLogErrorsLogicProps(log, sessionId)}
                    surface={surface}
                    onOpenRelatedErrors={onOpenRelatedErrors}
                />
            )}
            {distinctId && (
                <LemonTag
                    size="small"
                    className="bg-surface-primary min-w-0"
                    data-attr={`logs-${surface}-context-person`}
                >
                    <span className="sr-only">Person</span>
                    <PersonDisplay person={{ distinct_id: distinctId }} withIcon="sm" />
                </LemonTag>
            )}
            {sessionId && (
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={log.timestamp}
                    size="xsmall"
                    type="secondary"
                    openPlayerIn={RecordingPlayerType.Modal}
                    checkRecordingExists
                    data-attr={`logs-${surface}-context-recording`}
                />
            )}
            {missing.length > 0 && (
                <MissingLinkInvestigate log={log} missing={missing} surface={surface} onLeave={onLeave} />
            )}
        </div>
    )
}
