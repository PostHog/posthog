import { useActions, useValues } from 'kea'

import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { SessionErrorsBadge } from 'products/logs/frontend/components/VirtualizedLogsList/cells/SessionErrorsBadge'
import { SESSION_ERRORS_WIDTH } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getSessionIdFromLogAttributes } from 'products/logs/frontend/utils'

// The slot keeps its width on rows with no errors so the columns beside it stay aligned down the
// page as counts arrive.
export function SessionErrorsCell({ log }: { log: ParsedLogMessage }): JSX.Element {
    const { sessionErrorCounts } = useValues(logsViewerLogic)
    const { openLogDetails, setActiveTab } = useActions(logDetailsModalLogic)
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)

    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    // hasOwn, not a plain lookup: a session id that collides with an Object member would
    // otherwise read back an inherited function instead of a count.
    const errorCount = sessionId && Object.hasOwn(sessionErrorCounts, sessionId) ? sessionErrorCounts[sessionId] : 0

    return (
        <div className="flex items-center justify-center shrink-0" style={{ width: SESSION_ERRORS_WIDTH }}>
            {errorCount > 0 && (
                <SessionErrorsBadge
                    errorCount={errorCount}
                    onClick={() => {
                        // openLogDetails resets the drawer to its Details tab, so the tab selection
                        // has to follow it.
                        openLogDetails(log)
                        setActiveTab('related-errors')
                    }}
                />
            )}
        </div>
    )
}
