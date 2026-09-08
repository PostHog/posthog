import { useActions, useValues } from 'kea'

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
    const { openLogDetails, setLogDetailsTab } = useActions(logsViewerLogic)
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)

    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    const errorCount = sessionId ? (sessionErrorCounts[sessionId] ?? 0) : 0

    return (
        <div className="flex items-center justify-center shrink-0" style={{ width: SESSION_ERRORS_WIDTH }}>
            {errorCount > 0 && (
                <SessionErrorsBadge
                    errorCount={errorCount}
                    onClick={() => {
                        // openLogDetails resets the drawer to its Details tab, so the tab selection
                        // has to follow it.
                        openLogDetails(log)
                        setLogDetailsTab('related-errors')
                    }}
                />
            )}
        </div>
    )
}
