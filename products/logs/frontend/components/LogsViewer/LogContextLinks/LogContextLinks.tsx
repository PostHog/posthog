import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { buildLogErrorsLogicProps } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/Tabs/RelatedErrors/buildLogErrorsLogicProps'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getDistinctIdWithKey, getSessionIdFromLogAttributes } from 'products/logs/frontend/utils'
import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'
import { ViewTraceButton } from 'products/tracing/frontend/components/ViewTraceButton'
import { type ErrorScope, usableId } from 'products/tracing/frontend/errorCorrelation'

import { LogErrorCount } from './LogErrorCount'

export interface LogContextLinksProps {
    log: ParsedLogMessage
    /** Called when the error count is clicked, with the scope the count was taken on. */
    onOpenRelatedErrors: (scope: ErrorScope) => void
}

export function LogContextLinks({ log, onOpenRelatedErrors }: LogContextLinksProps): JSX.Element | null {
    const { configuredSessionIdKeys, configuredDistinctIdKeys } = useValues(logsConfigLogic)

    const traceId = usableId(log.trace_id)
    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    const distinctId = getDistinctIdWithKey(log.attributes, log.resource_attributes, configuredDistinctIdKeys)?.value

    if (!traceId && !sessionId && !distinctId) {
        return null
    }

    return (
        <div className="flex items-center gap-1 flex-wrap min-w-0">
            {traceId && (
                <ViewTraceButton
                    traceId={traceId}
                    spanId={log.span_id}
                    timestamp={log.timestamp}
                    size="xsmall"
                    type="secondary"
                    data-attr="logs-details-view-trace"
                />
            )}
            {(traceId || sessionId) && (
                <LogErrorCount
                    logicProps={buildLogErrorsLogicProps(log, sessionId)}
                    onOpenRelatedErrors={onOpenRelatedErrors}
                />
            )}
            {distinctId && (
                <LemonTag size="small" className="bg-surface-primary min-w-0" data-attr="logs-context-links-person">
                    <span className="sr-only">Person</span>
                    <PersonDisplay person={{ distinct_id: distinctId }} withIcon="sm" />
                </LemonTag>
            )}
            {sessionId && (
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={log.timestamp}
                    size="xsmall"
                    openPlayerIn={RecordingPlayerType.Modal}
                    checkRecordingExists
                    data-attr="logs-context-links-recording"
                />
            )}
        </div>
    )
}
