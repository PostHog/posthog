import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Link, Spinner } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { TabsContent } from 'lib/ui/quill'

import { SurroundingLogsPanel } from 'products/logs/frontend/components/SurroundingLogsPanel'
import { SURROUNDING_LOGS_WINDOW_MINUTES } from 'products/logs/frontend/utils'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from '../SubHeader'

export interface LogsTabProps {
    timestamp?: string
}

export function LogsTab({ timestamp }: LogsTabProps): JSX.Element {
    const { loading, issueId, logsScope } = useValues(exceptionCardLogic)
    const { setLogsScope } = useActions(exceptionCardLogic)
    const { sessionId } = useValues(errorPropertiesLogic)

    // Keyed by issue rather than by occurrence, so paging through an issue's occurrences keeps the
    // display settings and filters the user set on the previous one.
    const viewerId = `error-tracking-issue-${issueId}`
    const scopedSessionId = sessionId && logsScope === 'session' ? sessionId : undefined

    return (
        <TabsContent value="logs" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {loading ? (
                <div className="flex h-[300px] items-center justify-center">
                    <Spinner />
                </div>
            ) : (
                <>
                    <SubHeader className="justify-between gap-2">
                        <span className="truncate text-xs text-secondary">
                            Logs from {SURROUNDING_LOGS_WINDOW_MINUTES} minutes before and after this exception.{' '}
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
                                    { value: 'session', label: 'This session' },
                                    { value: 'window', label: 'All logs' },
                                ]}
                                data-attr="error-tracking-logs-scope"
                            />
                        )}
                    </SubHeader>
                    <div className="min-h-0 flex-1 overflow-hidden p-2">
                        <SurroundingLogsPanel id={viewerId} timestamp={timestamp} sessionId={scopedSessionId} />
                    </div>
                </>
            )}
        </TabsContent>
    )
}
