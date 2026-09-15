import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { TabsContent } from 'lib/ui/quill'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { EXCEPTION_LOGS_WINDOW_MINUTES, buildLogsSessionScope } from 'products/logs/frontend/utils'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from '../SubHeader'
import { TabSpinner } from '../TabSpinner'

export interface LogsTabProps {
    timestamp?: string
}

export function LogsTab({ timestamp }: LogsTabProps): JSX.Element {
    const { loading, issueId, logsScope } = useValues(exceptionCardLogic)
    const { setLogsScope } = useActions(exceptionCardLogic)
    const { sessionId } = useValues(errorPropertiesLogic)

    // logsViewerFiltersLogic compares `initialFilters` by identity and re-applies it whenever the
    // object changes, which resets the date range and any sparkline zoom the user set. So the
    // window is memoized on the occurrence alone, and the scope toggle only moves the session id.
    const { initialFilters } = useMemo(
        () => buildLogsSessionScope(undefined, timestamp, EXCEPTION_LOGS_WINDOW_MINUTES),
        [timestamp]
    )
    const scopedSessionId = sessionId && logsScope === 'session' ? sessionId : undefined

    return (
        <TabsContent value="logs" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {loading ? (
                <TabSpinner />
            ) : (
                <>
                    {/* The caption has to wrap rather than clip: truncating it in the narrow detail
                        pane would cut off the docs link, which is the only remedy offered when an
                        exception carries no session id. */}
                    <SubHeader className="h-auto min-h-9 justify-between gap-2 py-1">
                        <span className="min-w-0 text-xs text-secondary">
                            Logs from {EXCEPTION_LOGS_WINDOW_MINUTES} minutes before and after this exception.{' '}
                            {!sessionId && (
                                <>
                                    This exception has no session ID, so these are all logs in that window.{' '}
                                    <Link
                                        to="https://posthog.com/docs/logs/link-session-replay"
                                        target="_blank"
                                        className="text-xs"
                                    >
                                        Link your logs to sessions
                                    </Link>
                                </>
                            )}
                        </span>
                        {sessionId && (
                            <LemonSegmentedButton
                                size="xsmall"
                                value={logsScope}
                                onChange={setLogsScope}
                                options={[
                                    {
                                        value: 'session',
                                        label: 'This session',
                                        'data-attr': 'error-tracking-logs-scope-session',
                                    },
                                    {
                                        value: 'window',
                                        label: 'All logs',
                                        'data-attr': 'error-tracking-logs-scope-window',
                                    },
                                ]}
                                className="shrink-0"
                            />
                        )}
                    </SubHeader>
                    <div className="min-h-0 flex-1 overflow-hidden p-2">
                        {/* Keyed by issue rather than by occurrence, so paging through an issue's
                            occurrences keeps the filters and display settings set on the last one. */}
                        <LogsViewer
                            id={`error-tracking-issue-${issueId}`}
                            sessionId={scopedSessionId}
                            initialFilters={initialFilters}
                            showFullScreenButton={false}
                            defaultFacetRailCollapsed
                            defaultSparklineCollapsed
                        />
                    </div>
                </>
            )}
        </TabsContent>
    )
}
