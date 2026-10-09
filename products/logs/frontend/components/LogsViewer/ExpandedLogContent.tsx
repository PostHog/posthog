import { useValues } from 'kea'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { PropertyFilterType } from '~/types'

import { LogAttributes } from 'products/logs/frontend/components/LogsViewer/LogAttributes'
import { LogContextSelector } from 'products/logs/frontend/components/LogsViewer/LogContextSelector/LogContextSelector'
import { RelatedErrorsTab } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/Tabs/RelatedErrors'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getSessionIdFromLogAttributes } from 'products/logs/frontend/utils'
import { ViewTraceButton } from 'products/tracing/frontend/components/ViewTraceButton'

export interface ExpandedLogContentProps {
    log: ParsedLogMessage
}

export function ExpandedLogContent({ log }: ExpandedLogContentProps): JSX.Element {
    const { showSessionErrors, sessionErrorCounts } = useValues(logsViewerLogic)
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)

    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    // Skip the related errors query when the page lookup already found no errors for this session.
    const sessionHasNoErrors =
        !!sessionId && Object.hasOwn(sessionErrorCounts, sessionId) && !sessionErrorCounts[sessionId]
    const showRelatedErrors = showSessionErrors && !!sessionId && !sessionHasNoErrors

    return (
        <div className="flex flex-col gap-2 p-2 bg-primary border-t border-border">
            <div className="flex flex-wrap items-center gap-1">
                <ViewTraceButton
                    traceId={log.trace_id}
                    spanId={log.span_id}
                    timestamp={log.timestamp}
                    size="xsmall"
                    type="secondary"
                    data-attr="logs-expanded-view-trace"
                />
                {sessionId && (
                    <ViewRecordingButton
                        sessionId={sessionId}
                        timestamp={log.timestamp}
                        size="xsmall"
                        openPlayerIn={RecordingPlayerType.Modal}
                        checkRecordingExists
                        data-attr="logs-expanded-view-recording"
                    />
                )}
                <LogContextSelector log={log} size="xsmall" showLabel />
            </div>
            {showRelatedErrors && (
                <div className="bg-primary overflow-hidden rounded border border-border">
                    <div className="px-3 py-2 bg-bg-light border-b border-border">
                        <span className="text-xs font-semibold text-muted uppercase">Related errors</span>
                    </div>
                    <div className="p-2">
                        <RelatedErrorsTab logUuid={log.uuid} logTimestamp={log.timestamp} sessionId={sessionId} />
                    </div>
                </div>
            )}
            <LogAttributes
                attributes={log.attributes}
                type={PropertyFilterType.LogAttribute}
                logUuid={log.uuid}
                title="Log attributes"
            />
            <LogAttributes
                attributes={(log.resource_attributes ?? {}) as Record<string, string>}
                type={PropertyFilterType.LogResourceAttribute}
                logUuid={log.uuid}
                title="Resource attributes"
            />
        </div>
    )
}
