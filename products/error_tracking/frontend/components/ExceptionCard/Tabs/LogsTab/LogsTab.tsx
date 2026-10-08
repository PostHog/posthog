import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { TabsContent } from 'lib/ui/quill'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { EXCEPTION_LOGS_WINDOW_MINUTES, buildLogsSessionScope } from 'products/logs/frontend/utils'

import { exceptionCardLogic, type ExceptionLogsScope } from '../../exceptionCardLogic'
import { SubHeader } from '../SubHeader'
import { TabSpinner } from '../TabSpinner'
import {
    buildExceptionLogPinnedFilters,
    getAvailableExceptionLogScopes,
    getEffectiveExceptionLogScope,
} from './logScope'

const LOG_SCOPE_LABELS: Record<ExceptionLogsScope, string> = {
    trace: 'Whole trace',
    span: 'This span',
    session: 'This session',
    window: 'All logs',
}

export interface LogsTabProps {
    timestamp?: string
}

export function LogsTab({ timestamp }: LogsTabProps): JSX.Element {
    const { loading, issueId, logsScope } = useValues(exceptionCardLogic)
    const { setLogsScope } = useActions(exceptionCardLogic)
    const { sessionId, spanId, traceId } = useValues(errorPropertiesLogic)

    // logsViewerFiltersLogic re-applies `initialFilters` whenever the object identity changes, which
    // resets the date range the user set, so the window depends on the occurrence and not the scope.
    const { initialFilters } = useMemo(
        () => buildLogsSessionScope(undefined, timestamp, EXCEPTION_LOGS_WINDOW_MINUTES),
        [timestamp]
    )
    const { availableScopes, effectiveScope, pinnedFilters } = useMemo(() => {
        const correlationIds = { sessionId, spanId, traceId }
        const nextAvailableScopes = getAvailableExceptionLogScopes(correlationIds)
        const nextEffectiveScope = getEffectiveExceptionLogScope(logsScope, nextAvailableScopes)

        return {
            availableScopes: nextAvailableScopes,
            effectiveScope: nextEffectiveScope,
            pinnedFilters: buildExceptionLogPinnedFilters(nextEffectiveScope, correlationIds),
        }
    }, [logsScope, sessionId, spanId, traceId])
    const scopedSessionId = effectiveScope === 'session' ? sessionId : undefined
    const hasCorrelationScope = availableScopes.length > 1

    useEffect(() => {
        if (!loading && logsScope !== effectiveScope) {
            setLogsScope(effectiveScope)
        }
    }, [effectiveScope, loading, logsScope, setLogsScope])

    return (
        <TabsContent value="logs" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {loading ? (
                <TabSpinner />
            ) : (
                <>
                    {/* The caption wraps rather than truncates, because truncating it in a narrow
                        pane cuts off the docs link the no-correlation case depends on. */}
                    <SubHeader className="h-auto min-h-9 justify-between gap-2 py-1">
                        <span className="min-w-0 text-xs text-secondary">
                            Logs from {EXCEPTION_LOGS_WINDOW_MINUTES} minutes before and after this exception.{' '}
                            {!hasCorrelationScope && (
                                <>
                                    This exception has no trace or session ID, so these are all logs in that window.{' '}
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
                        {hasCorrelationScope && (
                            <LemonSelect<ExceptionLogsScope>
                                aria-label="Log scope"
                                size="xsmall"
                                value={effectiveScope}
                                onChange={setLogsScope}
                                options={availableScopes.map((scope) => ({
                                    value: scope,
                                    label: LOG_SCOPE_LABELS[scope],
                                    'data-attr': `error-tracking-logs-scope-${scope}`,
                                }))}
                                data-attr="error-tracking-logs-scope"
                                className="shrink-0"
                                dropdownPlacement="bottom-end"
                            />
                        )}
                    </SubHeader>
                    <div className="min-h-0 flex-1 overflow-hidden p-2">
                        {/* Keyed by issue, so paging through its occurrences keeps the user's filters. */}
                        <LogsViewer
                            id={`error-tracking-issue-${issueId}`}
                            sessionId={scopedSessionId}
                            pinnedFilters={pinnedFilters}
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
